"""HTTP adapters for the 2B protocol. Secrets are accepted in headers, never URLs."""
from functools import wraps
from uuid import UUID

from django.http import FileResponse, JsonResponse
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views.decorators.debug import sensitive_variables

from signaling import reservations as domain


class ReservationHeadersMissing(Exception):
    pass


def private(response):
    patch_cache_control(response, no_store=True, private=True)
    patch_vary_headers(response, ("Cookie",))
    return response


def failure(error):
    code = getattr(error, "code", "reservation_required")
    status = {
        "reservation_required": 428,
        "invalid_reservation_arguments": 400,
        "authentication_required": 401,
        "permission_denied": 403,
        "waypoint_not_found": 404,
        "reservation_occupied": 409,
        "reservation_credentials_invalid": 403,
        "reservation_generation_stale": 409,
        "reservation_expired": 409,
        "reservation_inactive": 409,
        "reservation_backend_unsupported": 503,
    }[code]
    messages = {
        "reservation_required": "Adquira uma reserva e envie as credenciais da interação.",
        "reservation_occupied": "Este waypoint está reservado por outra aquisição.",
        "reservation_expired": "A reserva expirou. Adquira uma nova reserva.",
        "reservation_generation_stale": "Esta aquisição foi substituída. Adquira uma nova reserva.",
        "reservation_credentials_invalid": "As credenciais não pertencem a esta aquisição.",
        "authentication_required": "Sua sessão terminou. Entre novamente.",
        "permission_denied": "Você não tem permissão para esta operação.",
        "waypoint_not_found": "Ponto de sinalização não encontrado.",
        "reservation_inactive": "Não há reserva ativa para esta aquisição.",
        "reservation_backend_unsupported": "Reservas exigem PostgreSQL neste ambiente.",
        "invalid_reservation_arguments": "Credenciais ou argumentos de reserva inválidos.",
    }
    return private(JsonResponse({"success": False, "code": code, "error": messages[code]},
                                status=status))


def identity(request):
    return domain.ReservationIdentity(request.session.session_key)


@sensitive_variables("token")
def credentials(request, *, optional=False):
    if any(key in request.GET for key in ("token", "reservation_token",
                                          "interaction_id", "generation")):
        raise domain.InvalidReservationArguments()
    token = request.headers.get("X-Waypoint-Token")
    interaction = request.headers.get("X-Waypoint-Interaction")
    generation = request.headers.get("X-Waypoint-Generation")
    if not any((token, interaction, generation)):
        if optional:
            return None
        raise ReservationHeadersMissing()
    if not all((token, interaction, generation)):
        raise domain.InvalidReservationArguments()
    try:
        if len(generation) > 19 or str(int(generation)) != generation:
            raise ValueError
        return domain.ReservationCredentials(UUID(interaction), int(generation), token)
    except (ValueError, AttributeError):
        raise domain.InvalidReservationArguments() from None


def reservation_required(*, write_only=False):
    """Authorization decorators must wrap this adapter, so permissions run first."""
    def decorate(view):
        @wraps(view)
        def checked(request, point_id, *args, **kwargs):
            if write_only and request.method == "GET":
                return view(request, point_id, *args, **kwargs)
            try:
                proof = credentials(request)
                with domain.validate_reservation(point_id=point_id, identity=identity(request),
                                                   credentials=proof):
                    response = view(request, point_id, *args, **kwargs)
                return private(response)
            except (domain.ReservationError, ReservationHeadersMissing) as error:
                return failure(error)
        return checked
    return decorate


def reservation_snapshot(*, survey=False):
    """Snapshot under a lock, slow read-only work outside, then fence delivery."""
    def decorate(view):
        @wraps(view)
        def checked(request, point_id, *args, **kwargs):
            try:
                proof = credentials(request)
                actor = identity(request)
                with domain.validate_reservation(point_id=point_id, identity=actor,
                                                   credentials=proof) as point:
                    request.reservation_point = point
                    if survey:
                        from signaling.surveys import capture_point_items
                        request.reservation_items = capture_point_items(point)
                response = view(request, point_id, *args, **kwargs)
                try:
                    with domain.validate_reservation(point_id=point_id, identity=actor,
                                                       credentials=proof):
                        pass
                except domain.ReservationError:
                    # Close the generated artifact without emitting request_finished
                    # for a response that will never be delivered.
                    if isinstance(response, FileResponse):
                        response.file_to_stream.close()
                    raise
                return private(response)
            except (domain.ReservationError, ReservationHeadersMissing) as error:
                return failure(error)
        return checked
    return decorate
