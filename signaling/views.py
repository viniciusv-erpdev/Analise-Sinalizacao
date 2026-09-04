import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from signaling.models import SignalingIntervention, SignalingPoint


COORDINATE_PRECISION = Decimal("0.000001")


def _read_json(request: HttpRequest) -> dict[str, object] | None:
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    return data if isinstance(data, dict) else None


def _validation_errors(error: ValidationError) -> dict[str, list[str]]:
    return {
        field: [message.message for message in messages]
        for field, messages in error.error_dict.items()
    }


def _point_payload(point: SignalingPoint) -> dict[str, object]:
    return {
        "id": point.id,
        "latitude": float(point.latitude),
        "longitude": float(point.longitude),
        "status": point.status,
        "interventions": [],
    }


def _intervention_payload(
    intervention: SignalingIntervention,
) -> dict[str, object]:
    return {
        "id": intervention.id,
        "type": intervention.type,
        "condition": intervention.condition,
        "notes": intervention.notes,
    }


def _normalize_coordinate(value: object) -> object:
    if value is None:
        return None

    try:
        coordinate = Decimal(str(value))
        if not coordinate.is_finite():
            return value
        return coordinate.quantize(COORDINATE_PRECISION)
    except (InvalidOperation, TypeError, ValueError):
        return value


@require_POST
def create_point(request: HttpRequest) -> JsonResponse:
    data = _read_json(request)
    if data is None:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    point = SignalingPoint(
        latitude=_normalize_coordinate(data.get("latitude")),
        longitude=_normalize_coordinate(data.get("longitude")),
        status=data.get("status"),
    )

    try:
        point.full_clean()
    except ValidationError as error:
        return JsonResponse(
            {"errors": _validation_errors(error)},
            status=400,
        )

    point.save()
    return JsonResponse(_point_payload(point), status=201)


@require_POST
def delete_point(request: HttpRequest, point_id: int) -> JsonResponse:
    point = get_object_or_404(SignalingPoint, pk=point_id)
    point.delete()
    return JsonResponse({"deleted": True, "id": point_id})


@require_POST
def update_point_status(request: HttpRequest, point_id: int) -> JsonResponse:
    point = get_object_or_404(SignalingPoint, pk=point_id)
    data = _read_json(request)
    if data is None:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    point.status = data.get("status")
    try:
        point.full_clean()
    except ValidationError as error:
        return JsonResponse(
            {"errors": _validation_errors(error)},
            status=400,
        )

    point.save(update_fields=["status", "updated_at"])
    return JsonResponse({"id": point.id, "status": point.status})


@require_POST
def save_intervention(request: HttpRequest, point_id: int) -> JsonResponse:
    point = get_object_or_404(SignalingPoint, pk=point_id)
    data = _read_json(request)
    if data is None:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    notes = data.get("notes", "")
    if not isinstance(notes, str):
        return JsonResponse(
            {"errors": {"notes": ["A observação deve ser um texto."]}},
            status=400,
        )

    candidate = SignalingIntervention(
        signaling_point=point,
        type=data.get("type"),
        condition=data.get("condition"),
        notes=notes,
    )
    try:
        candidate.full_clean(validate_constraints=False)
    except ValidationError as error:
        return JsonResponse(
            {"errors": _validation_errors(error)},
            status=400,
        )

    candidate.save()
    return JsonResponse(_intervention_payload(candidate), status=201)


@require_POST
def delete_intervention(
    request: HttpRequest,
    point_id: int,
    intervention_id: int,
) -> JsonResponse:
    intervention = get_object_or_404(
        SignalingIntervention,
        pk=intervention_id,
        signaling_point_id=point_id,
    )
    intervention.delete()
    return JsonResponse({"deleted": True, "id": intervention_id})


@require_POST
def update_intervention_condition(
    request: HttpRequest,
    point_id: int,
    intervention_id: int,
) -> JsonResponse:
    intervention = get_object_or_404(
        SignalingIntervention,
        pk=intervention_id,
        signaling_point_id=point_id,
    )
    data = _read_json(request)
    if data is None:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    intervention.condition = data.get("condition")
    try:
        intervention.full_clean()
    except ValidationError as error:
        return JsonResponse(
            {"errors": _validation_errors(error)},
            status=400,
        )

    intervention.save(update_fields=["condition", "updated_at"])
    return JsonResponse(_intervention_payload(intervention))


@require_POST
def update_intervention_notes(
    request: HttpRequest,
    point_id: int,
    intervention_id: int,
) -> JsonResponse:
    intervention = get_object_or_404(
        SignalingIntervention,
        pk=intervention_id,
        signaling_point_id=point_id,
    )
    data = _read_json(request)
    if data is None:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    notes = data.get("notes")
    if not isinstance(notes, str):
        return JsonResponse(
            {"errors": {"notes": ["A observação deve ser um texto."]}},
            status=400,
        )

    intervention.notes = notes
    intervention.save(update_fields=["notes", "updated_at"])
    return JsonResponse(_intervention_payload(intervention))
