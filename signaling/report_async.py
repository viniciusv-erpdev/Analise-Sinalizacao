"""Owner-only HTTP projection. No launch authority or operational identifiers."""
from signaling.models import ReportLaunch, ReportDispatchDelivery


def progress(attempt):
    # The caller MUST use finalization.get_attempt(user_id), never raw UUID access.
    launch = ReportLaunch.objects.filter(identity__attempt_reference=attempt.pk).first()
    phase = attempt.state
    if attempt.state == "ADMITTED":
        phase = "AWAITING_DISPATCH"
        if launch:
            phase = "LAUNCH_REQUESTED"
            if (launch.state != "REQUESTED" or
                    ReportDispatchDelivery.objects.filter(launch=launch).exists()):
                phase = "LAUNCH_UNCERTAIN"
    return {"publication_phase": phase,
            "requires_reconciliation": phase in ("LAUNCH_UNCERTAIN", "FAILED", "INTERRUPTED")}
