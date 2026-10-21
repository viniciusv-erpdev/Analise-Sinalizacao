"""Read-only reconciliation uses POST to keep inventories out of URL limits."""
import json
import re

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from signaling.authorization import signaling_access
from signaling.synchronization import waypoint_changes


@require_POST
@signaling_access()
def synchronize(request):
    try:
        data = json.loads(request.body)
        known = data["known"]
        if set(data) != {"known"} or not isinstance(known, dict) or any(
            not re.fullmatch(r"[1-9][0-9]*", key)
            or len(key) > 19
            or not isinstance(value, str)
            or not re.fullmatch(r"[0-9a-f]{64}", value)
            for key, value in known.items()
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        response = JsonResponse({"success": False, "code": "invalid_sync_inventory",
                                 "error": "Inventário de waypoints inválido."}, status=400)
    else:
        response = JsonResponse(waypoint_changes(known))
    response["Cache-Control"] = "private, no-store"
    return response
