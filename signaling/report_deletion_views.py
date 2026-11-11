"""Backend-only, permission-based permanent deletion. No staff gate or GET mutation."""
import json
from uuid import UUID
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from signaling.reservation_http import private
from signaling import reservations
from signaling.report_deletion import delete_report, ReportDeletionError
from signaling.models import ReportDeletion


@transaction.non_atomic_requests
@require_POST
def delete_official_report(request, report_id):
    if not request.user.is_authenticated:
        return private(JsonResponse({"success":False, "code":"authentication_required"}, status=401))
    # Check authorization before parsing payload or looking up any report.
    from signaling.report_read_access import can_delete_official_reports
    if not can_delete_official_reports(request.user):
        return private(JsonResponse({"success":False, "code":"permission_denied"}, status=403))
    try:
        if request.content_type != "application/json":
            raise ValueError
        data = json.loads(request.body)
        if not isinstance(data, dict) or set(data) != {"operation_id", "confirm_number"}:
            raise ValueError
        operation_id = UUID(data["operation_id"])
        if operation_id.version != 4 or not isinstance(data["confirm_number"], str) or len(data["confirm_number"]) > 20:
            raise ValueError
        audit = delete_report(user=request.user, report_id=report_id, operation_id=operation_id,
                              confirm_number=data["confirm_number"])
        complete = audit.cleanup_state == ReportDeletion.State.COMPLETE
        return private(JsonResponse({"success":complete, "report_deleted":True,
            "operation_id":str(audit.pk), "number":audit.official_number,
            "cleanup_state":audit.cleanup_state, "code":"report_deleted" if complete else "deletion_cleanup_pending"},
            status=200 if complete else 202))
    except (ValueError, TypeError, AttributeError):
        return private(JsonResponse({"success":False, "code":"invalid_deletion_payload"}, status=400))
    except ReportDeletionError as error:
        return private(JsonResponse({"success":False, "code":error.code}, status=error.status))
    except (ImproperlyConfigured, reservations.ReservationBackendUnsupported):
        return private(JsonResponse({"success":False, "code":"deletion_unavailable"}, status=503))
