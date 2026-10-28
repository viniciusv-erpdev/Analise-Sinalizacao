"""Synchronous homologation service. Never hold database locks across conversion.

Lock order: waypoint -> reservation -> draft -> attempt -> annual counter.
Execution IDs fence interrupted/late workers. Persisted snapshots never change.
"""
from datetime import timedelta
import hashlib
import json
from uuid import UUID, uuid4
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.utils import timezone

from signaling import reservations as r
from signaling.authorization import VIEW, REPORT
from signaling.models import (TechnicalReport, TechnicalReportVersion, ReportArtifact,
    ReportAnnualCounter, ReportFinalizationAttempt as Attempt, WaypointReportDraft)
from signaling.pdf_conversion import (convert_docx_to_pdf, validate_pdf, ConversionOptions, PDFConversionError)
from signaling.report_filters import parse_individual_report_filters
from signaling.report_snapshots import (canonical, digest, point_source, validate_form, render_snapshot,
    OFFICIAL_TIMEZONE, SCHEMA_VERSION, MAX_SNAPSHOT_BYTES)
from signaling.report_storage import PrivateReportStorage, ArtifactStorageError
from signaling.surveys import build_signaling_survey_from_items

FINALIZE = "signaling.finalize_technicalreport"
ACTIVE = (Attempt.State.PROCESSING, Attempt.State.STORING)


class FinalizationError(Exception):
    def __init__(self, code, status=409, attempt=None):
        self.code, self.status, self.attempt = code, status, attempt
        super().__init__(code)


def require_enabled():
    if not settings.REPORT_FINALIZATION_ENABLED:
        raise FinalizationError("finalization_disabled", 503)
    # Reserving numbers must never use SQLite or an ambient request transaction.
    r._require_locking_backend()
    if connection.in_atomic_block:
        raise FinalizationError("finalization_requires_autocommit", 503)


def official_issued_at():
    return timezone.now().astimezone(OFFICIAL_TIMEZONE)


def _actor(user_id):
    try:
        user = get_user_model().objects.get(pk=user_id)
    except get_user_model().DoesNotExist:
        raise r.ReservationPermissionDenied() from None
    if not user.is_active or not user.has_perms((VIEW, REPORT, FINALIZE)):
        raise r.ReservationPermissionDenied()
    return user


def _source(point, user_id):
    _actor(user_id)
    draft = WaypointReportDraft.objects.select_for_update().filter(signaling_point=point).first()
    return point_source(point, draft)


def _fence(point_id, identity, credentials, user_id):
    # Recheck after ALL waits, including draft/attempt/counter locks.
    with r.validate_reservation(point_id=point_id, identity=identity, credentials=credentials):
        _actor(user_id)


def _counter(year):
    # Unique PK + get_or_create savepoint handles concurrent first annual row.
    ReportAnnualCounter.objects.get_or_create(year=year)
    counter = ReportAnnualCounter.objects.select_for_update().get(year=year)
    if counter.last_reserved >= 9999:
        raise FinalizationError("annual_number_exhausted")
    counter.last_reserved += 1
    counter.save(update_fields=["last_reserved"])
    return counter.last_reserved


def describe(attempt):
    version = attempt.version
    return {"success": attempt.state == Attempt.State.FINALIZED,
            "attempt_id": str(attempt.pk), "report_id": str(version.report_id),
            "version": version.version, "number": version.report.official_number,
            "state": attempt.state, "error_code": attempt.error_code,
            "issued_at": version.issued_at.astimezone(OFFICIAL_TIMEZONE).isoformat(),
            "finalized_at": version.finalized_at.isoformat() if version.finalized_at else None}


def get_attempt(attempt_id, user_id):
    # No UUID-based access bypass, including for staff without explicit policy.
    _actor(user_id)
    try:
        return Attempt.objects.select_related("version__report").get(pk=attempt_id, requested_by_id=user_id)
    except Attempt.DoesNotExist:
        raise FinalizationError("finalization_not_found", 404) from None


def _existing(key, user_id, fingerprint):
    attempt = Attempt.objects.select_related("version__report").filter(idempotency_key=key).first()
    if attempt:
        if attempt.requested_by_id != user_id:
            raise FinalizationError("finalization_not_found", 404)
        if attempt.request_sha256 != fingerprint:
            raise FinalizationError("idempotency_key_conflict", attempt=attempt)
    return attempt


def finalize(*, point_id, identity, credentials, user_id, key, expected_revision,
             parameters, analysis_state, photos):
    require_enabled()
    _actor(user_id)
    if not isinstance(key, UUID) or key.version != 4 or type(expected_revision) is not int or expected_revision < 0:
        raise ValidationError({"request": "UUID v4 and nonnegative expected_revision required"})
    query = {name: parameters.getlist(name) for name in sorted(parameters)}
    fingerprint = digest({"point_id": point_id, "revision": expected_revision,
                          "filters": query, "photos": [metadata for metadata, _ in photos]})
    prior = _existing(key, user_id, fingerprint)
    if prior:
        return prior  # Read-only replay; never retries conversion implicitly.
    storage = PrivateReportStorage()  # Validate configuration before reserving a number.
    with r.validate_reservation(point_id=point_id, identity=identity, credentials=credentials) as point:
        source = _source(point, user_id)
        if source["draft"]["revision"] != expected_revision:
            raise FinalizationError("draft_revision_conflict")
        fields = validate_form(source["draft"]["fields"])
        actor = _actor(user_id)
        author = {"id": actor.pk, "username": actor.get_username(), "full_name": actor.get_full_name()}
    if not isinstance(analysis_state, dict) or analysis_state.get("view_mode") != "individual" or not isinstance(analysis_state.get("map_data"), list):
        raise ValidationError({"analysis": "An individual analysis is required"})
    accidents = analysis_state["map_data"]
    filters = parse_individual_report_filters(parameters, accidents, analysis_state.get("analysis_id"))
    survey = build_signaling_survey_from_items(point, filters.apply(accidents), point_items=source["items"])
    survey["filters"] = filters.presentation()
    snapshot = {"schema_version": SCHEMA_VERSION, "renderer_version": 1, "source": source,
                "form": fields, "author": author, "survey": survey,
                "filters": {"years": filters.years, "months": filters.months,
                            "categories": filters.categories, "gravity": filters.gravity},
                "photos": [metadata for metadata, _ in photos]}
    if len(canonical(snapshot)) > MAX_SNAPSHOT_BYTES:
        raise ValidationError({"analysis": "Selected report snapshot exceeds 8 MiB"})
    try:
        with r.validate_reservation(point_id=point_id, identity=identity, credentials=credentials) as point:
            if digest(_source(point, user_id)) != digest(source):
                raise FinalizationError("report_source_changed")
            prior = _existing(key, user_id, fingerprint)
            if prior:
                return prior
            issued_at = official_issued_at()
            sequence = _counter(issued_at.year)
            _fence(point_id, identity, credentials, user_id)
            report = TechnicalReport.objects.create(waypoint=point, waypoint_history=source["point"],
                year=issued_at.year, sequence=sequence, number_reserved_at=issued_at)
            snapshot.update(issued_at=issued_at.isoformat(), official_number=report.official_number)
            # Normalize dates, tuples, Decimal etc before freezing JSON/hash.
            snapshot = json.loads(canonical(snapshot))
            version = TechnicalReportVersion.objects.create(report=report, snapshot=snapshot,
                schema_version=SCHEMA_VERSION, snapshot_sha256=digest(snapshot), source_sha256=digest(source),
                author_id=user_id, author_identity=author, issued_at=issued_at)
            attempt = Attempt.objects.create(version=version, requested_by_id=user_id,
                idempotency_key=key, request_sha256=fingerprint,
                deadline=timezone.now() + timedelta(seconds=settings.REPORT_EXECUTION_SECONDS))
    except IntegrityError:
        # A globally reused key on different points can race the initial lookup.
        prior = _existing(key, user_id, fingerprint)
        if prior:
            return prior
        raise
    return _execute(attempt, identity, credentials, user_id, photos, storage)


def _assert_run(attempt_id, execution_id):
    attempt = Attempt.objects.select_for_update().get(pk=attempt_id)
    if attempt.execution_id != execution_id or attempt.state not in ACTIVE or attempt.deadline <= timezone.now():
        raise FinalizationError("execution_superseded", attempt=attempt)
    return attempt


def _store(attempt, storage, kind, data, *, ordinal=0, metadata=None):
    metadata = metadata or {}
    extension = {"PDF": "pdf", "DOCX": "docx", "PHOTO": "jpg" if metadata.get("format") == "JPEG" else "png"}[kind]
    key = f"{attempt.version_id}/{attempt.execution_id}/{uuid4()}.{extension}"
    storage.save(key, data)
    # Verify actual persisted bytes before creating any database reference.
    # Never unlink on failure: commit acknowledgement may be ambiguous. Aged,
    # unreferenced files are handled only by conservative reconciliation.
    size, sha256 = len(data), hashlib.sha256(data).hexdigest()
    storage.read(SimpleNamespace(storage_key=key, size=size, sha256=sha256))
    with transaction.atomic():
        _assert_run(attempt.pk, attempt.execution_id)
        artifact = ReportArtifact.objects.create(version_id=attempt.version_id, kind=kind, ordinal=ordinal,
            storage_key=key, download_name=f"{attempt.version.report.official_number}-v{attempt.version.version}" +
                (f"-foto-{ordinal + 1}" if kind == "PHOTO" else "") + f".{extension}",
            content_type={"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                          "jpg": "image/jpeg", "png": "image/png"}[extension],
            size=size, sha256=sha256, metadata=metadata)
    return artifact



def _error_status(error):
    if isinstance(error, r.ReservationError):
        return {"authentication_required": 401, "permission_denied": 403,
                "reservation_credentials_invalid": 403, "waypoint_not_found": 404,
                "invalid_reservation_arguments": 400, "reservation_backend_unsupported": 503}.get(error.code, 409)
    return error.status if isinstance(error, FinalizationError) else 503


def _execute(attempt, identity, credentials, user_id, photos, storage):
    version = attempt.version
    try:
        if digest(version.snapshot) != version.snapshot_sha256:
            raise FinalizationError("snapshot_integrity_failed")
        supplied = {meta["ordinal"]: (meta, data) for meta, data in photos}
        photo_bytes = []
        for metadata in version.snapshot["photos"]:
            ordinal = metadata["ordinal"]
            artifact = version.artifacts.filter(kind="PHOTO", ordinal=ordinal).first()
            if artifact:
                data = storage.read(artifact)
            else:
                if ordinal not in supplied or supplied[ordinal][0] != metadata:
                    raise FinalizationError("original_photos_required", attempt=attempt)
                data = supplied[ordinal][1]
                _store(attempt, storage, "PHOTO", data, ordinal=ordinal, metadata=metadata)
            if hashlib.sha256(data).hexdigest() != metadata["sha256"]:
                raise ArtifactStorageError("artifact_integrity_failed")
            photo_bytes.append(data)
        # No PostgreSQL atomic block, reservation lock, HTTP response, or session read here.
        docx = render_snapshot(version.snapshot, photo_bytes)
        pdf = convert_docx_to_pdf(docx, options=ConversionOptions(
            executable=settings.REPORT_LIBREOFFICE_EXECUTABLE,
            timeout_seconds=settings.REPORT_CONVERSION_TIMEOUT))
        validate_pdf(pdf)
        with transaction.atomic():
            current = _assert_run(attempt.pk, attempt.execution_id)
            current.state = Attempt.State.STORING
            current.save(update_fields=["state", "updated_at"])
        _store(attempt, storage, "DOCX", docx)
        _store(attempt, storage, "PDF", pdf)
        point_id = version.report.waypoint_id
        if point_id is None:
            raise FinalizationError("waypoint_not_found", 404)
        with r.validate_reservation(point_id=point_id, identity=identity, credentials=credentials) as point:
            if digest(_source(point, user_id)) != version.source_sha256:
                raise FinalizationError("report_source_changed")
            current = _assert_run(attempt.pk, attempt.execution_id)
            _fence(point_id, identity, credentials, user_id)
            finished = timezone.now()
            version.finalized_at = finished
            version.save(update_fields=["finalized_at"])
            version.report.number_assigned_at = finished
            version.report.save(update_fields=["number_assigned_at"])
            current.state, current.error_code = Attempt.State.FINALIZED, ""
            current.save(update_fields=["state", "error_code", "updated_at"])
        return Attempt.objects.select_related("version__report").get(pk=attempt.pk)
    except Exception as error:
        code = (error.code if isinstance(error, (FinalizationError, r.ReservationError, PDFConversionError))
                else str(error) if isinstance(error, ArtifactStorageError) else "finalization_failed")
        # Never persist exception messages, paths, session data or converter diagnostics.
        Attempt.objects.filter(pk=attempt.pk, execution_id=attempt.execution_id, state__in=ACTIVE).update(
            state=Attempt.State.FAILED, error_code=code, updated_at=timezone.now())
        raise FinalizationError(code, _error_status(error), attempt=attempt) from None


def retry(*, attempt_id, user_id, identity, credentials, photos=()):
    require_enabled()
    attempt = get_attempt(attempt_id, user_id)
    if attempt.state == Attempt.State.FINALIZED:
        return attempt
    point_id = attempt.version.report.waypoint_id
    if point_id is None:
        raise FinalizationError("waypoint_not_found", 404, attempt)
    storage = PrivateReportStorage()
    if photos and [metadata for metadata, _ in photos] != attempt.version.snapshot["photos"]:
        raise FinalizationError("original_photos_mismatch", attempt=attempt)
    with r.validate_reservation(point_id=point_id, identity=identity, credentials=credentials) as point:
        if digest(_source(point, user_id)) != attempt.version.source_sha256:
            raise FinalizationError("report_source_changed", attempt=attempt)
        current = Attempt.objects.select_for_update().get(pk=attempt_id)
        _fence(point_id, identity, credentials, user_id)
        if current.state == Attempt.State.FINALIZED:
            return get_attempt(attempt_id, user_id)
        if current.state in ACTIVE and current.deadline > timezone.now():
            return get_attempt(attempt_id, user_id)
        # Remove only unpublished derivative metadata. Files become reconciliation candidates.
        # Keep original photos and the immutable snapshot/number across retries.
        current.version.artifacts.filter(kind__in=("PDF", "DOCX")).delete()
        current.execution_id = uuid4()
        current.deadline = timezone.now() + timedelta(seconds=settings.REPORT_EXECUTION_SECONDS)
        current.state, current.error_code = Attempt.State.PROCESSING, ""
        current.save(update_fields=["execution_id", "deadline", "state", "error_code", "updated_at"])
        attempt = current
    return _execute(attempt, identity, credentials, user_id, photos, storage)
