"""Explicit physical deletion and durable, retryable private-file cleanup.

No conversion or filesystem mutation inside the metadata-deletion transaction.
NOWAIT report/version/attempt locks avoid reversing the finalizer's attempt ->
report lock order: contention is a conflict, never a wait/deadlock or takeover.
"""
import hashlib
from uuid import UUID
from django.contrib.auth import get_user_model
from django.db import connection, transaction, DatabaseError
from django.utils import timezone
from signaling import reservations
from signaling.models import (TechnicalReport, TechnicalReportVersion, ReportArtifact,
    ReportFinalizationAttempt as Attempt, ReportAnnualCounter, ReportDeletion, DeletedReportKey)
from signaling.report_read_access import can_delete_official_reports
from signaling.report_storage import PrivateReportStorage, ArtifactStorageError


class ReportDeletionError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def _actor(user):
    if not can_delete_official_reports(user):
        raise ReportDeletionError("permission_denied", 403)
    try:
        return get_user_model().objects.get(pk=user.pk)
    except get_user_model().DoesNotExist:
        raise ReportDeletionError("permission_denied", 403) from None


def _boundary():
    reservations._require_locking_backend()
    if connection.in_atomic_block:
        raise ReportDeletionError("deletion_requires_autocommit", 503)


def _database_error(error):
    busy = getattr(error.__cause__, "sqlstate", None) == "55P03"
    return ReportDeletionError("deletion_conflict" if busy else "deletion_database_unavailable", 409 if busy else 503)


def _version_keys(storage, version_ids):
    # IDs are database-owned; canonical UUIDs also defend corrupted cleanup manifests.
    for value in version_ids:
        if str(UUID(value)) != value:
            raise ArtifactStorageError("invalid_version_namespace")
        directory = storage.root / value
        if directory.is_symlink():
            raise ArtifactStorageError("unsafe_storage_path")
        for path in directory.glob("*/*"):
            key = path.relative_to(storage.root).as_posix()
            storage._path(key)
            if path.is_file():
                yield key


def _validate_key(storage, key, version_ids):
    storage._path(key)
    if key.split("/")[0] not in version_ids:
        raise ArtifactStorageError("foreign_artifact_namespace")


def delete_report(*, user, report_id, operation_id, confirm_number):
    _actor(user)
    _boundary()
    storage = PrivateReportStorage()
    try:
        with transaction.atomic():
            claimed = ReportDeletion.objects.filter(pk=operation_id).first()
            if claimed and claimed.report_id != report_id:
                raise ReportDeletionError("deletion_operation_conflict")
            prior = ReportDeletion.objects.filter(report_id=report_id).first()
            if prior:
                if prior.official_number != confirm_number:
                    raise ReportDeletionError("confirmation_mismatch", 400)
                operation_id = prior.pk
            else:
                if ReportDeletion.objects.filter(pk=operation_id).exists():
                    raise ReportDeletionError("deletion_operation_conflict")
                report = TechnicalReport.objects.select_for_update(nowait=True).filter(pk=report_id).first()
                if report is None:
                    # Another deletion can commit after the initial idempotency lookup.
                    if ReportDeletion.objects.filter(report_id=report_id).exists():
                        raise ReportDeletionError("deletion_conflict")
                    raise ReportDeletionError("report_not_found", 404)
                versions = list(TechnicalReportVersion.objects.select_for_update(nowait=True)
                                .filter(report=report).only("id", "report_id", "finalized_at").order_by("pk"))
                attempts = list(Attempt.objects.select_for_update(nowait=True)
                                .filter(version__report=report).only("id", "version_id", "state", "idempotency_key").order_by("pk"))
                if not any(v.finalized_at and report.number_assigned_at and
                           any(a.version_id == v.pk and a.state == Attempt.State.FINALIZED for a in attempts)
                           for v in versions):
                    raise ReportDeletionError("report_not_found", 404)
                # Even overdue active executions require explicit existing reconciliation first.
                if any(a.state in (Attempt.State.PROCESSING, Attempt.State.STORING) for a in attempts):
                    raise ReportDeletionError("publication_in_progress")
                actor = _actor(user)  # revalidate permission after every lock acquisition
                if report.official_number != confirm_number:
                    raise ReportDeletionError("confirmation_mismatch", 400)
                ids = [str(v.pk) for v in versions]
                keys = list(ReportArtifact.objects.filter(version__report=report).values_list("storage_key", flat=True))
                keys = sorted(set(keys) | set(_version_keys(storage, ids)))
                for key in keys:
                    _validate_key(storage, key, ids)
                    if ReportArtifact.objects.filter(storage_key=key).exclude(version__report=report).exists():
                        raise ArtifactStorageError("shared_artifact")
                # Never decrement the counter; heal a missing/lagging counter under lock.
                ReportAnnualCounter.objects.get_or_create(year=report.year, defaults={"last_reserved":report.sequence})
                counter = ReportAnnualCounter.objects.select_for_update().get(year=report.year)
                if counter.last_reserved < report.sequence:
                    counter.last_reserved = report.sequence
                    counter.save(update_fields=["last_reserved"])
                actor = _actor(user)  # counter creation/locking can also wait
                audit = ReportDeletion.objects.create(id=operation_id, report_id=report.pk,
                    official_number=report.official_number, deleted_at=timezone.now(),
                    deleted_by=actor, deleted_by_username=actor.get_username(), pending_keys=keys, version_ids=ids)
                DeletedReportKey.objects.bulk_create([DeletedReportKey(deletion=audit,
                    key_sha256=hashlib.sha256(str(a.idempotency_key).encode("ascii")).hexdigest()) for a in attempts])
                # Explicit child-first removal honors PROTECT; no SQL or immutable-field updates.
                Attempt.objects.filter(version__report=report).delete()
                ReportArtifact.objects.filter(version__report=report).delete()
                TechnicalReportVersion.objects.filter(report=report).delete()
                report.delete()
        # Reached only after commit acknowledgement. Ambiguous commits never unlink files.
    except DatabaseError as error:
        raise _database_error(error) from None
    except (ArtifactStorageError, OSError, ValueError):
        raise ReportDeletionError("unsafe_deletion_storage", 409) from None
    return cleanup_deletion(operation_id=operation_id, storage=storage)


def cleanup_deletion(*, operation_id, storage=None):
    """Internal recovery entry point, also used by the explicit operator command."""
    _boundary()
    storage = storage or PrivateReportStorage()
    try:
        with transaction.atomic():
            audit = ReportDeletion.objects.select_for_update(nowait=True).get(pk=operation_id)
            if audit.cleanup_state == ReportDeletion.State.COMPLETE:
                return audit
            try:
                keys = sorted(set(audit.pending_keys) | set(_version_keys(storage, audit.version_ids)))
                audit.pending_keys = keys
                while audit.pending_keys:
                    key = audit.pending_keys[0]
                    _validate_key(storage, key, audit.version_ids)
                    if ReportArtifact.objects.filter(storage_key=key).exists():
                        raise ArtifactStorageError("referenced_artifact")
                    storage.delete(key)  # absent files are a successful, idempotent cleanup
                    audit.pending_keys.pop(0)
                audit.version_ids = []
                audit.cleanup_state = ReportDeletion.State.COMPLETE
                audit.cleanup_finished_at = timezone.now()
                audit.error_code = ""
            except (ArtifactStorageError, OSError, ValueError):
                audit.cleanup_state = ReportDeletion.State.FAILED
                audit.error_code = "private_cleanup_failed"
            audit.save(update_fields=["pending_keys", "version_ids", "cleanup_state", "cleanup_finished_at", "error_code"])
            return audit
    except DatabaseError as error:
        # Files may already be absent; persisted outbox still supports safe repeated cleanup.
        raise _database_error(error) from None
