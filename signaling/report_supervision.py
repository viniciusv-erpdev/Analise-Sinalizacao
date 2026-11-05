"""Persistent launch intent + atomic startup binding. No privileged launcher/recovery."""
from dataclasses import dataclass
from pathlib import Path
import re
from uuid import UUID, uuid4

from django.conf import settings
from django.db import connection
from django.utils import timezone

from signaling import report_admission as admission, report_systemd_runtime as runtime
from signaling.models import ReportExecutionIdentity as Identity, ReportFinalizationAttempt as Attempt
from signaling.report_finalization import FinalizationError
from signaling import reservations


@dataclass(frozen=True)
class LaunchContext:
    identity_id: UUID
    runtime: runtime.RuntimeIdentity


def require_enabled():
    if not settings.REPORT_SYSTEMD_SUPERVISION_ENABLED:
        raise FinalizationError("supervision_disabled", 503)
    try:
        reservations._require_locking_backend()
    except reservations.ReservationBackendUnsupported as error:
        raise FinalizationError(error.code, 503) from None
    if connection.in_atomic_block:
        raise FinalizationError("supervision_requires_autocommit", 503)


def prepare(*, attempt_id, expected_execution_id):
    require_enabled()
    host = runtime.host_identity()
    release = settings.REPORT_EXECUTOR_RELEASE_ID
    user = settings.REPORT_EXECUTOR_SYSTEMD_USER
    if (not re.fullmatch(r"[0-9a-f]{40,64}", release)
            or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,63}", user) or user == "root"):
        raise FinalizationError("supervision_configuration_invalid", 503)
    with admission.coordination():
        from signaling.report_operations import assert_open
        assert_open()
        attempt = admission.assert_execution(attempt_id, expected_execution_id, states=(Attempt.State.ADMITTED,))
        prior = Identity.objects.filter(attempt_reference=attempt_id, expected_execution_id=expected_execution_id).first()
        if prior:
            if (prior.host_id != host.host_id or prior.boot_id != host.boot_id
                    or prior.release_id != release or prior.release_root != str(Path(settings.BASE_DIR).resolve())
                    or prior.service_user != user or prior.bound_at):
                raise FinalizationError("supervision_plan_conflict")
            return prior
        key = uuid4()
        return Identity.objects.create(id=key, attempt=attempt, attempt_reference=attempt_id,
            expected_execution_id=expected_execution_id, host_id=host.host_id, boot_id=host.boot_id,
            unit_name=f"rtsv-report-{key.hex}.service", release_id=release,
            release_root=str(Path(settings.BASE_DIR).resolve()), service_user=user)


def context(identity_id):
    require_enabled()
    try:
        identity = Identity.objects.get(pk=identity_id)
    except Identity.DoesNotExist:
        raise FinalizationError("supervision_identity_not_found", 404) from None
    if identity.bound_at or identity.attempt_id is None:
        raise FinalizationError("supervision_identity_already_used")
    return identity.attempt_id, LaunchContext(identity.pk, runtime.capture(identity))


def bind(attempt, context):
    """Called only under the executor's slot/attempt transaction, before rendering."""
    if not settings.REPORT_SYSTEMD_SUPERVISION_ENABLED or not connection.in_atomic_block:
        raise FinalizationError("supervision_binding_unavailable", 503)
    from signaling.report_operations import assert_open
    assert_open()
    identity = Identity.objects.select_for_update().filter(pk=context.identity_id).first()
    if identity is None:
        raise FinalizationError("supervision_identity_not_found", 404)
    observed = context.runtime
    from signaling.models import ReportLaunch
    launch = ReportLaunch.objects.select_for_update().filter(identity=identity).first()
    from signaling.report_operations import execution_contract
    from signaling.report_snapshots import digest
    if launch and (launch.state not in (ReportLaunch.State.UNCERTAIN, ReportLaunch.State.CONFIRMED)
            or launch.dispatch_id is None or launch.invocation_id not in (None, observed.invocation_id)
            or launch.release_id != identity.release_id
            or launch.contract_sha256 != digest(attempt.execution_contract)
            or attempt.execution_contract != execution_contract()
            or launch.release.execution_contract != attempt.execution_contract):
        raise FinalizationError("launch_binding_invalid")
    # Active deliveries require the independently consumed authority receipt.
    # Preserve pre-integration internal/manual contracts for historical tests.
    from signaling.models import ReportDispatchDelivery, ReportLauncherReceipt
    delivery = ReportDispatchDelivery.objects.filter(launch=launch).first() if launch else None
    if delivery:
        receipt = ReportLauncherReceipt.objects.filter(launch=launch).first()
        if (not receipt or receipt.pk != delivery.pk
                or receipt.dispatch_id != launch.dispatch_id
                or receipt.barrier_generation != delivery.barrier_generation
                or receipt.host_id != observed.host.host_id or receipt.boot_id != observed.host.boot_id
                or receipt.manifest_sha256 != launch.release.manifest_sha256
                or receipt.bundle_sha256 != launch.release.bundle_sha256):
            raise FinalizationError("launch_receipt_invalid")
    if (identity.attempt_id != attempt.pk or identity.attempt_reference != attempt.pk
            or identity.expected_execution_id != attempt.execution_id or identity.bound_at
            or identity.host_id != observed.host.host_id or identity.boot_id != observed.host.boot_id
            or identity.unit_name != observed.unit_name):
        raise FinalizationError("supervision_binding_conflict")
    identity.invocation_id = observed.invocation_id
    identity.cgroup_path, identity.cgroup_inode = observed.cgroup_path, observed.cgroup_inode
    identity.main_pid, identity.process_start_ticks = observed.main_pid, observed.process_start_ticks
    identity.bound_at = timezone.now()
    identity.save(update_fields=["invocation_id", "cgroup_path", "cgroup_inode", "main_pid", "process_start_ticks", "bound_at"])
    return identity.execution_id


def verify(context):
    identity = Identity.objects.filter(pk=context.identity_id).first()
    if identity is None:
        raise FinalizationError("supervision_identity_not_found", 404)
    persisted = runtime.RuntimeIdentity(runtime.HostIdentity(identity.host_id, identity.boot_id),
        identity.unit_name, identity.invocation_id, identity.cgroup_path, identity.cgroup_inode,
        identity.main_pid, identity.process_start_ticks)
    if not identity.bound_at or runtime.capture(identity) != persisted or persisted != context.runtime:
        raise FinalizationError("supervision_runtime_changed", 503)
