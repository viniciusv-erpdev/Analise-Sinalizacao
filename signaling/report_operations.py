"""Persistent operational contracts only. No systemd, polling or termination proof.

All mutations serialize with admission.coordination. The future trusted launcher
must commit begin_dispatch before invoking systemd, and never resend that ticket.
Callers are trusted internal administrative components, not HTTP authorization.
"""
from uuid import UUID, uuid4
import re

from django.db import connection
from django.utils import timezone

from signaling.models import (ReportDeploymentBarrier as Barrier, ReportLaunch as Launch,
    ReportOperationalEvent as Event, ReportReleaseAuthorization as Release,
    ReportExecutionIdentity as Identity, ReportFinalizationAttempt as Attempt)
from signaling.report_finalization import FinalizationError
from signaling.report_snapshots import SCHEMA_VERSION, digest


def execution_contract():
    # Bump the relevant protocol whenever persisted-input/rendering semantics change.
    return {"admission": 1, "snapshot": SCHEMA_VERSION, "renderer": 1, "launcher": 1}


def _boundary():
    from signaling import reservations
    reservations._require_locking_backend()
    if connection.in_atomic_block:
        raise FinalizationError("operations_requires_autocommit", 503)


def _locked_barrier():
    if not connection.in_atomic_block:
        raise FinalizationError("operations_requires_transaction", 503)
    Barrier.objects.get_or_create(pk=1, defaults={"generation": UUID(int=0)})
    return Barrier.objects.select_for_update().get(pk=1)


def assert_open():
    """Caller holds coordination for writes; also safe as an early read guard."""
    if Barrier.objects.exclude(state=Barrier.State.OPEN).exists():
        raise FinalizationError("publication_maintenance", 503)


def assert_admission_allowed():
    assert_open()
    # There is deliberately no proof-verified terminal state in this stage.
    if Launch.objects.exists() or Identity.objects.exists():
        raise FinalizationError("publication_busy")


def _event(event_id, subject, kind, actor, details, *, result=None):
    if not all(isinstance(value, UUID) for value in (event_id, subject, actor)):
        raise FinalizationError("operational_identifier_invalid", 400)
    fingerprint = digest({"subject": str(subject), "kind": kind, "actor": str(actor), "details": details})
    previous = Event.objects.filter(pk=event_id).first()
    if previous:
        if previous.fingerprint != fingerprint:
            raise FinalizationError("operational_idempotency_conflict")
        return previous, False
    return Event.objects.create(id=event_id, subject=subject, kind=kind, actor=actor,
        details=details if result is None else result, fingerprint=fingerprint), True


def request_launch(*, identity_id):
    """Persist a request, NOT permission to call systemd. Same identity replays."""
    _boundary()
    from signaling import report_admission as admission
    with admission.coordination():
        previous = Launch.objects.filter(identity_id=identity_id).first()
        if previous:
            return previous
        assert_open()
        if Launch.objects.exists():
            raise FinalizationError("operational_reconciliation_required")
        if Identity.objects.exclude(pk=identity_id).exists():
            raise FinalizationError("operational_reconciliation_required")
        identity = Identity.objects.select_for_update().filter(pk=identity_id).first()
        if not identity or identity.bound_at:
            raise FinalizationError("launch_identity_invalid")
        attempt = admission.assert_execution(identity.attempt_id, identity.expected_execution_id,
                                            states=(Attempt.State.ADMITTED,))
        release = Release.objects.filter(pk=identity.release_id).first()
        contract = attempt.execution_contract
        if (not release or contract != execution_contract() or release.execution_contract != contract
                or attempt.version.schema_version != contract.get("snapshot")
                or not re.fullmatch(r"[0-9a-f]{40,64}", release.release_id)
                or not all(re.fullmatch(r"[0-9a-f]{64}", value)
                           for value in (release.bundle_sha256, release.manifest_sha256))):
            raise FinalizationError("launch_release_incompatible")
        launch = Launch.objects.create(identity=identity, release=release, contract_sha256=digest(contract))
        return launch


def begin_dispatch(*, launch_id, actor, event_id):
    """One caller receives a fresh ticket. A replay NEVER grants another start.

    Return None on exact replay. Once this commits, absence of acknowledgement,
    timeout or process death leaves UNCERTAIN. No reset/retry API is provided.
    """
    _boundary()
    from signaling import report_admission as admission
    with admission.coordination():
        launch = Launch.objects.select_for_update().select_related("identity", "release").get(pk=launch_id)
        _, fresh = _event(event_id, launch.pk, "DISPATCH_BEGIN", actor, {})
        if not fresh:
            return None
        assert_open()
        identity = launch.identity
        attempt = admission.assert_execution(identity.attempt_id, identity.expected_execution_id,
                                             states=(Attempt.State.ADMITTED,))
        if (launch.state != Launch.State.REQUESTED or identity.bound_at
                or launch.contract_sha256 != digest(attempt.execution_contract)
                or attempt.execution_contract != execution_contract()
                or launch.release.execution_contract != attempt.execution_contract
                or launch.release_id != identity.release_id):
            raise FinalizationError("launch_transition_invalid")
        launch.state = Launch.State.UNCERTAIN
        launch.dispatch_id, launch.dispatch_started_at = uuid4(), timezone.now()
        launch.save(update_fields=["state", "dispatch_id", "dispatch_started_at"])
        return launch.dispatch_id


def observe_launch(*, launch_id, dispatch_id, actor, event_id, invocation_id=None,
                   job_id=None, terminal_result=None):
    """Trusted observer contract. A terminal observation is NOT termination proof.

    No free-form paths/output; retain identity and bounded result codes only.
    A terminal event does not release ownership or authorize deployment.
    """
    _boundary()
    if ((invocation_id is not None and (not isinstance(invocation_id, UUID) or not invocation_id.int))
            or (invocation_id is None and (job_id is None or terminal_result is not None))
            or (job_id is not None and (type(job_id) is not int or job_id <= 0))
            or (terminal_result is not None and terminal_result not in
                {"success", "signal", "exit-code", "timeout", "oom-kill", "resources", "unknown"})):
        raise FinalizationError("launch_observation_invalid", 400)
    from signaling import report_admission as admission
    with admission.coordination():
        launch = Launch.objects.select_for_update().select_related("identity").get(pk=launch_id)
        kind = "TERMINAL_OBSERVED" if terminal_result is not None else "START_CONFIRMED" if invocation_id else "JOB_OBSERVED"
        details = {"dispatch_id": str(dispatch_id), "invocation_id": str(invocation_id) if invocation_id else None,
                   "job_id": job_id, "result": terminal_result}
        _, fresh = _event(event_id, launch.pk, kind, actor, details)
        if not fresh:
            return launch
        if (launch.dispatch_id != dispatch_id or launch.state == Launch.State.REQUESTED
                or (invocation_id is not None and launch.invocation_id not in (None, invocation_id))
                or (invocation_id is not None and launch.identity.invocation_id not in (None, invocation_id))
                or (launch.job_id is not None and job_id not in (None, launch.job_id))
                or (launch.state == Launch.State.TERMINAL_OBSERVED and terminal_result is None)):
            raise FinalizationError("launch_transition_invalid")
        if terminal_result is not None and Event.objects.filter(subject=launch.pk,
                kind="TERMINAL_OBSERVED").exclude(pk=event_id).exclude(details__result=terminal_result).exists():
            raise FinalizationError("launch_observation_conflict")
        if invocation_id is not None:
            launch.invocation_id = invocation_id
        if job_id is not None:
            launch.job_id = job_id
        if terminal_result is None and invocation_id is not None:
            launch.state = Launch.State.CONFIRMED
            launch.confirmed_at = launch.confirmed_at or timezone.now()
        elif terminal_result is not None:
            launch.state = Launch.State.TERMINAL_OBSERVED
            launch.terminal_observed_at = launch.terminal_observed_at or timezone.now()
        launch.save()
        return launch


def _assert_quiescent(slot):
    if (slot.attempt_id or Attempt.objects.exclude(state=Attempt.State.FINALIZED).exists()
            or Identity.objects.exists() or Launch.objects.exists()):
        raise FinalizationError("deployment_not_quiescent")
    # Identity existence is conservative: even an unbound plan may have started.
    # No terminal verifier exists yet, so none can be silently cleared here.


def transition_barrier(*, expected_generation, target, actor, event_id):
    """OPEN -> DRAINING -> DEPLOYING -> OPEN, or explicit cancel DRAINING -> OPEN.

    Closing never expires. Canceling drain does not claim deploy safety; reopening
    after DEPLOYING requires quiescence. No recovery/slot mutation is performed.
    """
    _boundary()
    if target not in Barrier.State.values:
        raise FinalizationError("deployment_transition_invalid")
    from signaling import report_admission as admission
    with admission.coordination() as slot:
        barrier = _locked_barrier()
        if Event.objects.filter(pk=event_id).exists():
            event, _ = _event(event_id, expected_generation, "BARRIER_" + target, actor, {})
            return event.details["generation"]
        if barrier.generation != expected_generation:
            raise FinalizationError("deployment_generation_stale")
        allowed = {Barrier.State.OPEN: {Barrier.State.DRAINING},
                   Barrier.State.DRAINING: {Barrier.State.OPEN, Barrier.State.DEPLOYING},
                   Barrier.State.DEPLOYING: {Barrier.State.OPEN}}
        if target not in allowed[barrier.state]:
            raise FinalizationError("deployment_transition_invalid")
        if target == Barrier.State.DEPLOYING or barrier.state == Barrier.State.DEPLOYING:
            _assert_quiescent(slot)
        barrier.state, barrier.generation = target, uuid4()
        barrier.save(update_fields=["state", "generation", "updated_at"])
        result = str(barrier.generation)
        _event(event_id, expected_generation, "BARRIER_" + target, actor, {}, result={"generation": result})
        return result


def barrier_status():
    """Read-only; missing singleton means default OPEN, never creates rows."""
    return Barrier.objects.filter(pk=1).values("state", "generation", "updated_at").first() or {
        "state": Barrier.State.OPEN, "generation": UUID(int=0), "updated_at": None}
