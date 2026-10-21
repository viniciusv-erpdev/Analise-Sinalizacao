import json
from uuid import UUID

from django.http import JsonResponse
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from signaling import reservations as domain
from signaling.authorization import signaling_access
from signaling.reservation_http import credentials, failure, identity, private, ReservationHeadersMissing


def guard(view):
    from functools import wraps

    @wraps(view)
    def checked(request, point_id):
        try:
            if any(key in request.GET for key in (
                    "token", "reservation_token", "interaction_id", "generation")):
                raise domain.InvalidReservationArguments()
            return private(view(request, point_id))
        except (domain.ReservationError, ReservationHeadersMissing) as error:
            return failure(error)
    return checked


@require_POST
@signaling_access()
@guard
@sensitive_variables()
def acquire(request, point_id):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict) or set(data) != {"interaction_id"}:
            raise ValueError
        interaction = UUID(data["interaction_id"])
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
        raise domain.InvalidReservationArguments() from None
    grant = domain.acquire_reservation(point_id=point_id, identity=identity(request),
                                       interaction_id=interaction)
    return JsonResponse({
        "success": True, "point_id": point_id, "state": "reserved_self",
        "token": grant.credentials.token,
        "interaction_id": str(grant.credentials.interaction_id),
        "generation": grant.credentials.generation,
        "expires_at": grant.expires_at.isoformat(),
    }, status=201)


@require_POST
@signaling_access()
@guard
def renew(request, point_id):
    grant = domain.renew_reservation(point_id=point_id, identity=identity(request),
                                     credentials=credentials(request))
    return JsonResponse({"success": True, "point_id": point_id, "state": "reserved_self",
                         "generation": grant.credentials.generation,
                         "expires_at": grant.expires_at.isoformat()})


@require_POST
@signaling_access()
@guard
def release(request, point_id):
    released = domain.release_reservation(point_id=point_id, identity=identity(request),
                                          credentials=credentials(request))
    return JsonResponse({"success": True, "point_id": point_id, "released": released})


@require_GET
@signaling_access()
@guard
def status(request, point_id):
    state = domain.get_reservation_status(point_id=point_id, identity=identity(request),
                                          credentials=credentials(request, optional=True))
    return JsonResponse({"success": True, "point_id": point_id, "state": state.state,
                         "generation": state.generation,
                         "expires_at": state.expires_at.isoformat() if state.expires_at else None})
