"""Internal persistent admission. No HTTP route, executor or automatic takeover.

Lock order: coordination -> slot -> waypoint -> reservation -> draft -> counter.
The transaction lock serializes admission/cleanup only; durable slot ownership
survives commit, connection loss and process restart. Deadlines never release it.
"""
from contextlib import contextmanager
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction, DatabaseError
from django.utils import timezone

from signaling import reservations as r, report_finalization as f
from signaling.models import (
    ReportPublicationSlot, ReportFinalizationAttempt as Attempt,
    TechnicalReport, TechnicalReportVersion, ReportArtifact, WaypointReservation,
)
from signaling.report_snapshots import canonical, digest, prepare_photos, SCHEMA_VERSION
from signaling.report_storage import PrivateReportStorage

# Application-owned two-int advisory namespace; NOT a session lock or lease.
COORDINATION_KEY = (182736, 1)


def require_enabled():
    if not settings.REPORT_ADMISSION_ENABLED:
        raise f.FinalizationError("admission_disabled", 503)
    r._require_locking_backend()
    if connection.in_atomic_block:
        raise f.FinalizationError("admission_requires_autocommit", 503)


@contextmanager
def coordination(*, wait=False):
    """Nonblocking PostgreSQL transaction mutex, also used by orphan cleanup."""
    r._require_locking_backend()
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                operation = "pg_advisory_xact_lock" if wait else "pg_try_advisory_xact_lock"
                cursor.execute(f"SELECT {operation}(%s, %s)", COORDINATION_KEY)
                acquired = cursor.fetchone()[0]
                if not wait and not acquired:
                    raise f.FinalizationError("publication_busy")
            ReportPublicationSlot.objects.get_or_create(pk=1)
            slot = ReportPublicationSlot.objects.select_for_update(nowait=True).get(pk=1)
            yield slot
    except DatabaseError as error:
        if getattr(error.__cause__, "sqlstate", None) == "55P03":
            raise f.FinalizationError("publication_busy") from None
        raise


def _fingerprint(point_id, key, expected_revision, parameters, photos):
    if (not isinstance(key, UUID) or key.version != 4
            or type(expected_revision) is not int or expected_revision < 0):
        raise ValidationError({"request": "UUID v4 and nonnegative expected_revision required"})
    return digest({"point_id": point_id, "revision": expected_revision,
                   "filters": {name: parameters.getlist(name) for name in sorted(parameters)},
                   "photos": [metadata for metadata, _ in photos]})


def _persist_photos(attempt, photos, storage):
    for metadata, data in photos:
        extension = "jpg" if metadata["format"] == "JPEG" else "png"
        key = f"{attempt.version_id}/{attempt.execution_id}/{uuid4()}.{extension}"
        storage.save(key, data)
        storage.read(SimpleNamespace(storage_key=key, size=len(data), sha256=metadata["sha256"]))
        ReportArtifact.objects.create(version=attempt.version, kind="PHOTO",
            ordinal=metadata["ordinal"], storage_key=key,
            download_name=f"{attempt.version.report.official_number}-v1-foto-{metadata['ordinal'] + 1}.{extension}",
            content_type=metadata["content_type"], size=len(data),
            sha256=metadata["sha256"], metadata=metadata)


def admit(*, point_id, identity, credentials, user_id, key, expected_revision,
          parameters, analysis_state, photos=()):
    """Return the durable attempt; accepts prepared (metadata, bytes) photos.

    Same fingerprint semantics as finalize. Authentication/permissions are checked
    on every call; a known key is a read-only replay and needs no live reservation.
    Successful return means all original inputs and global ownership committed.
    No deletion on exceptions: file/commit acknowledgement can be ambiguous.
    """
    require_enabled()
    user_id = f._actor(user_id).pk
    fingerprint = _fingerprint(point_id, key, expected_revision, parameters, photos)
    prior = f._existing(key, user_id, fingerprint)
    if prior:
        return prior
    try:
        with coordination() as slot:
            # Recheck after obtaining the global mutex, before busy/number/files.
            prior = f._existing(key, user_id, fingerprint)
            if prior:
                return prior
            # Legacy timeout reconciliation is not proof that its process died.
            if slot.attempt_id or Attempt.objects.filter(state__in=(*f.ACTIVE, Attempt.State.INTERRUPTED)).exists():
                raise f.FinalizationError("publication_busy")
            storage = PrivateReportStorage()
            # Internal callers must not be able to admit incomplete/fake metadata.
            if any(not isinstance(data, bytes) for _, data in photos):
                raise ValidationError({"photos": "Prepared photo bytes required"})
            verified = prepare_photos([SimpleUploadedFile("original", data) for _, data in photos])
            if [meta for meta, _ in verified] != [meta for meta, _ in photos]:
                raise ValidationError({"photos": "Original photo metadata mismatch"})
            source, snapshot = f.prepare_intention(point_id=point_id, identity=identity,
                credentials=credentials, user_id=user_id, expected_revision=expected_revision,
                parameters=parameters, analysis_state=analysis_state, photos=verified)
            with r.validate_reservation(point_id=point_id, identity=identity, credentials=credentials) as point:
                if WaypointReservation.objects.get(signaling_point=point).user_id != int(user_id):
                    raise r.ReservationPermissionDenied()
                if digest(f._source(point, user_id)) != digest(source):
                    raise f.FinalizationError("report_source_changed")
                issued_at = f.official_issued_at()
                sequence = f._counter(issued_at.year)
                f._fence(point_id, identity, credentials, user_id)
                report = TechnicalReport.objects.create(waypoint=point, waypoint_history=source["point"],
                    year=issued_at.year, sequence=sequence, number_reserved_at=issued_at)
                snapshot.update(issued_at=issued_at.isoformat(), official_number=report.official_number)
                snapshot = json.loads(canonical(snapshot))
                version = TechnicalReportVersion.objects.create(report=report, snapshot=snapshot,
                    schema_version=SCHEMA_VERSION, snapshot_sha256=digest(snapshot),
                    source_sha256=digest(source), author_id=user_id,
                    author_identity=snapshot["author"], issued_at=issued_at)
                attempt = Attempt.objects.create(version=version, requested_by_id=user_id,
                    idempotency_key=key, request_sha256=fingerprint, state=Attempt.State.ADMITTED,
                    admitted_at=timezone.now(), deadline=None)
                _persist_photos(attempt, verified, storage)
                # File writes can take time. Authorization is valid at admission
                # commit; it is never required again by the future executor.
                f._fence(point_id, identity, credentials, user_id)
                slot.attempt, slot.execution_id = attempt, attempt.execution_id
                slot.save(update_fields=["attempt", "execution_id"])
            return attempt
    except f.FinalizationError as error:
        if error.code == "publication_busy":
            # A competing identical request may have committed meanwhile.
            prior = f._existing(key, user_id, fingerprint)
            if prior:
                return prior
        raise


def retry_admission(*, attempt_id, user_id):
    """Replay admission, never steal an expired/failed executor's ownership.

    Stage 1 deliberately has no recovery/takeover API: failure after execution
    starts requires the future supervisor's proof of termination.
    """
    require_enabled()
    attempt = f.get_attempt(attempt_id, user_id)
    if attempt.state == Attempt.State.FINALIZED:
        return attempt
    with coordination() as slot:
        if slot.attempt_id and slot.attempt_id != attempt.pk:
            raise f.FinalizationError("publication_busy")
        current = Attempt.objects.select_for_update().get(pk=attempt.pk)
        if (slot.attempt_id != current.pk or slot.execution_id != current.execution_id
                or current.admitted_at is None):
            raise f.FinalizationError("admission_reconciliation_required", attempt=current)
        if current.state != Attempt.State.ADMITTED:
            raise f.FinalizationError("admission_reconciliation_required", attempt=current)
        return current


def assert_execution(attempt_id, execution_id, *, states=f.ACTIVE):
    """Future executor's transactional fence, required at EVERY result commit.

    Caller must keep this transaction through its metadata/result writes. No
    session, reservation, mutable waypoint or application deadline is consulted.
    This grants no start/takeover/release operation in stage 1.
    """
    r._require_locking_backend()
    if not connection.in_atomic_block:
        raise f.FinalizationError("execution_requires_transaction", 503)
    slot = ReportPublicationSlot.objects.select_for_update().filter(pk=1).first()
    attempt = Attempt.objects.select_for_update().select_related("version__report").filter(pk=attempt_id).first()
    if (not slot or not attempt or slot.attempt_id != attempt_id
            or slot.execution_id != execution_id or attempt.execution_id != execution_id
            or attempt.admitted_at is None or attempt.state not in states):
        raise f.FinalizationError("execution_superseded")
    from signaling.models import ReportExecutionIdentity
    identity = ReportExecutionIdentity.objects.filter(execution_id=execution_id).first()
    if identity and (identity.attempt_id != attempt.pk or identity.attempt_reference != attempt.pk or not identity.bound_at):
        raise f.FinalizationError("execution_superseded")
    snapshot = attempt.version.snapshot
    if (digest(snapshot) != attempt.version.snapshot_sha256
            or digest(snapshot.get("source")) != attempt.version.source_sha256
            or snapshot.get("official_number") != attempt.version.report.official_number
            or snapshot.get("author") != attempt.version.author_identity
            or snapshot.get("schema_version") != attempt.version.schema_version):
        raise f.FinalizationError("snapshot_integrity_failed")
    return attempt


def load_inputs(*, attempt_id, execution_id):
    """Read/verify durable originals for a future executor, without HTTP state."""
    with transaction.atomic():
        attempt = assert_execution(attempt_id, execution_id, states=(Attempt.State.ADMITTED, *f.ACTIVE))
        snapshot = attempt.version.snapshot
        artifacts = list(attempt.version.artifacts.filter(kind="PHOTO").order_by("ordinal"))
    if [a.metadata for a in artifacts] != snapshot["photos"]:
        raise f.FinalizationError("admission_inputs_incomplete")
    storage = PrivateReportStorage()
    photos = [storage.read(artifact) for artifact in artifacts]
    if any(hashlib.sha256(data).hexdigest() != meta["sha256"]
           for meta, data in zip(snapshot["photos"], photos)):
        raise f.FinalizationError("admission_inputs_incomplete")
    with transaction.atomic():
        assert_execution(attempt_id, execution_id, states=(Attempt.State.ADMITTED, *f.ACTIVE))
    return snapshot, photos
