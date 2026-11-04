"""One-shot independent executor. No HTTP, reservation, lease or automatic retry.

All metadata writes lock slot -> attempt -> version/report. Rendering, conversion
and filesystem I/O run without database transactions. Failed ownership is retained.
"""
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction, DatabaseError
from django.utils import timezone

from signaling import report_admission as admission, report_finalization as finalization
from signaling import reservations
from signaling.models import ReportFinalizationAttempt as Attempt, ReportArtifact
from signaling.pdf_conversion import convert_docx_to_pdf, validate_pdf, ConversionOptions, PDFConversionError
from signaling.report_snapshots import render_snapshot
from signaling.report_storage import PrivateReportStorage, ArtifactStorageError

ExecutionError = finalization.FinalizationError


class ExecutorInterrupted(BaseException):
    """Raised by the command's SIGTERM/SIGINT handler; converter finally cleans up."""


def require_enabled():
    if not settings.REPORT_EXECUTOR_ENABLED:
        raise ExecutionError("executor_disabled", 503)
    try:
        reservations._require_locking_backend()
    except reservations.ReservationBackendUnsupported as error:
        raise ExecutionError(error.code, 503) from None
    except ImproperlyConfigured:
        raise ExecutionError("execution_configuration_invalid", 503) from None
    if connection.in_atomic_block:
        raise ExecutionError("executor_requires_autocommit", 503)


def claim(attempt_id=None, *, supervision=None):
    """ADMITTED -> PROCESSING once, rotating both fencing identifiers atomically.

    Empty slot returns None only for discovery. Explicit finalized attempts replay
    their stored result without conversion or ownership changes.
    """
    require_enabled()
    with admission.coordination() as slot:
        if attempt_id is not None:
            prior = Attempt.objects.select_related("version__report").filter(pk=attempt_id).first()
            if prior is None:
                raise ExecutionError("finalization_not_found", 404)
            if prior.admitted_at is not None and prior.state == Attempt.State.FINALIZED:
                return prior
            if slot.attempt_id != attempt_id:
                raise ExecutionError("execution_not_slot_owner")
        elif slot.attempt_id is None:
            return None
        attempt = admission.assert_execution(slot.attempt_id, slot.execution_id,
            states=(Attempt.State.ADMITTED, Attempt.State.PROCESSING, Attempt.State.STORING,
                    Attempt.State.FAILED, Attempt.State.INTERRUPTED))
        if attempt.state in finalization.ACTIVE:
            raise ExecutionError("execution_already_started")
        if attempt.state != Attempt.State.ADMITTED:
            raise ExecutionError("admission_reconciliation_required")
        if (attempt.version.finalized_at or attempt.version.report.number_assigned_at
                or attempt.version.artifacts.filter(kind__in=("DOCX", "PDF")).exists()):
            raise ExecutionError("admission_reconciliation_required")
        from signaling.models import ReportExecutionIdentity
        if supervision is not None:
            from signaling.report_supervision import bind
            execution_id = bind(attempt, supervision)
        else:
            if (settings.REPORT_SYSTEMD_SUPERVISION_ENABLED or ReportExecutionIdentity.objects.filter(
                    attempt_reference=attempt.pk, expected_execution_id=attempt.execution_id).exists()):
                raise ExecutionError("execution_supervision_required")
            execution_id = uuid4()
        attempt.execution_id = slot.execution_id = execution_id
        attempt.state, attempt.error_code = Attempt.State.PROCESSING, ""
        attempt.save(update_fields=["execution_id", "state", "error_code", "updated_at"])
        slot.save(update_fields=["execution_id"])
        return attempt


def _record_failure(attempt, code, state=Attempt.State.FAILED):
    """Best effort, conditional on current ownership. Never release or take over.

    Deliberately independent of snapshot validation: corrupt inputs must still be
    reportable. Database/commit ambiguity leaves durable state for reconciliation.
    """
    try:
        with admission.coordination() as slot:
            current = Attempt.objects.select_for_update().filter(pk=attempt.pk).first()
            if (current is not None and slot.attempt_id == current.pk
                    and slot.execution_id == attempt.execution_id == current.execution_id
                    and current.state in finalization.ACTIVE):
                current.state, current.error_code = state, code
                current.save(update_fields=["state", "error_code", "updated_at"])
    except (DatabaseError, ExecutionError):
        # Preserve the original safe error; never reconnect to release anything.
        pass


def _complete(attempt, artifacts):
    """Commit publication and slot release together; no file I/O in this scope."""
    with admission.coordination() as slot:
        current = admission.assert_execution(attempt.pk, attempt.execution_id, states=(Attempt.State.STORING,))
        registered = list(ReportArtifact.objects.filter(version=current.version,
            kind__in=("DOCX", "PDF")).order_by("kind").values_list("pk", "kind", "ordinal", "sha256", "size"))
        expected = sorted((a.pk, a.kind, a.ordinal, a.sha256, a.size) for a in artifacts)
        if sorted(registered) != expected or {a.kind for a in artifacts} != {"DOCX", "PDF"}:
            raise ExecutionError("execution_artifacts_incomplete")
        finished = timezone.now()
        current.version.finalized_at = finished
        current.version.save(update_fields=["finalized_at"])
        current.version.report.number_assigned_at = finished
        current.version.report.save(update_fields=["number_assigned_at"])
        current.state, current.error_code = Attempt.State.FINALIZED, ""
        current.save(update_fields=["state", "error_code", "updated_at"])
        slot.attempt, slot.execution_id = None, None
        slot.save(update_fields=["attempt", "execution_id"])
    return current


def execute(attempt_id=None, *, supervision=None):
    """Process at most the slot's single admitted intention, returning its result.

    Claim commits before any rendering. A crash after claim is not retryable by
    this API. The existing reconciliation command cannot reclaim admitted runs.
    """
    try:
        attempt = claim(attempt_id, supervision=supervision)
    except DatabaseError:
        raise ExecutionError("execution_database_state_unknown", 503) from None
    if attempt is None or attempt.state == Attempt.State.FINALIZED:
        return attempt
    try:
        storage = PrivateReportStorage()
        snapshot, photos = admission.load_inputs(attempt_id=attempt.pk, execution_id=attempt.execution_id)
        docx = render_snapshot(snapshot, photos)
        if supervision is not None:
            from signaling.report_supervision import verify
            verify(supervision)
        # A loss of ownership while rendering must not start LibreOffice.
        with transaction.atomic():
            admission.assert_execution(attempt.pk, attempt.execution_id, states=(Attempt.State.PROCESSING,))
        pdf = convert_docx_to_pdf(docx, options=ConversionOptions(
            executable=settings.REPORT_LIBREOFFICE_EXECUTABLE,
            timeout_seconds=settings.REPORT_CONVERSION_TIMEOUT))
        validate_pdf(pdf)
        with transaction.atomic():
            current = admission.assert_execution(attempt.pk, attempt.execution_id,
                states=(Attempt.State.PROCESSING,))
            current.state = Attempt.State.STORING
            current.save(update_fields=["state", "updated_at"])
        artifacts = [finalization._store(attempt, storage, kind, data,
            assert_run=admission.assert_execution) for kind, data in (("DOCX", docx), ("PDF", pdf))]
        if supervision is not None:
            verify(supervision)
        return _complete(attempt, artifacts)
    except DatabaseError:
        # The last commit may have succeeded; do not downgrade FINALIZED or free
        # a PROCESSING/STORING slot. An explicit read must resolve this ambiguity.
        raise ExecutionError("execution_database_state_unknown", 503) from None
    except (ExecutorInterrupted, KeyboardInterrupt, SystemExit):
        _record_failure(attempt, "execution_interrupted", Attempt.State.INTERRUPTED)
        raise ExecutionError("execution_interrupted", 503) from None
    except Exception as error:
        if isinstance(error, (ExecutionError, PDFConversionError)):
            code = error.code
        elif isinstance(error, ArtifactStorageError):
            code = "execution_storage_failed"
        elif isinstance(error, ImproperlyConfigured):
            code = "execution_configuration_invalid"
        else:
            code = "execution_failed"
        _record_failure(attempt, code)
        raise ExecutionError(code, 503) from None
