import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from signaling.models import SignalingIntervention, SignalingPoint
from signaling.surveys import (
    ANALYSIS_SESSION_KEY,
    build_signaling_survey_from_items,
)


COORDINATE_PRECISION = Decimal("0.000001")


def point_report(request: HttpRequest, point_id: int):
    point = get_object_or_404(
        SignalingPoint.objects.prefetch_related("interventions"),
        pk=point_id,
    )
    analysis_state = request.session.get(ANALYSIS_SESSION_KEY)
    survey = None
    if (
        isinstance(analysis_state, dict)
        and analysis_state.get("view_mode") == "individual"
        and isinstance(analysis_state.get("map_data"), list)
    ):
        accidents = analysis_state["map_data"]
        survey = build_signaling_survey_from_items(point, accidents)

    return render(
        request,
        "signaling/report.html",
        {"point": point, "survey": survey},
    )


def _read_json(request: HttpRequest) -> dict[str, object] | None:
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    return data if isinstance(data, dict) else None


def _api_not_found(resource: str) -> JsonResponse:
    return JsonResponse(
        {"success": False, "error": f"{resource} não encontrado."},
        status=404,
    )


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
        return JsonResponse(
            {"success": False, "error": "JSON inválido."},
            status=400,
        )

    point = SignalingPoint(
        latitude=_normalize_coordinate(data.get("latitude")),
        longitude=_normalize_coordinate(data.get("longitude")),
        status=data.get("status"),
    )

    try:
        point.full_clean()
    except ValidationError as error:
        return JsonResponse(
            {"success": False, "errors": _validation_errors(error)},
            status=400,
        )

    point.save()
    return JsonResponse(
        {"success": True, **_point_payload(point)},
        status=201,
    )


@require_POST
def delete_point(request: HttpRequest, point_id: int) -> JsonResponse:
    try:
        point = SignalingPoint.objects.get(pk=point_id)
    except SignalingPoint.DoesNotExist:
        return _api_not_found("Ponto de sinalização")
    point.delete()
    return JsonResponse({"success": True, "deleted": True, "id": point_id})


@require_POST
def update_point_status(request: HttpRequest, point_id: int) -> JsonResponse:
    try:
        point = SignalingPoint.objects.get(pk=point_id)
    except SignalingPoint.DoesNotExist:
        return _api_not_found("Ponto de sinalização")
    data = _read_json(request)
    if data is None:
        return JsonResponse(
            {"success": False, "error": "JSON inválido."},
            status=400,
        )

    point.status = data.get("status")
    try:
        point.full_clean()
    except ValidationError as error:
        return JsonResponse(
            {"success": False, "errors": _validation_errors(error)},
            status=400,
        )

    point.save(update_fields=["status", "updated_at"])
    return JsonResponse(
        {"success": True, "id": point.id, "status": point.status}
    )


@require_POST
def save_intervention(request: HttpRequest, point_id: int) -> JsonResponse:
    try:
        point = SignalingPoint.objects.get(pk=point_id)
    except SignalingPoint.DoesNotExist:
        return _api_not_found("Ponto de sinalização")
    data = _read_json(request)
    if data is None:
        return JsonResponse(
            {"success": False, "error": "JSON inválido."},
            status=400,
        )

    notes = data.get("notes", "")
    if not isinstance(notes, str):
        return JsonResponse(
            {"success": False, "errors": {"notes": ["A observação deve ser um texto."]}},
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
            {"success": False, "errors": _validation_errors(error)},
            status=400,
        )

    candidate.save()
    return JsonResponse(
        {"success": True, **_intervention_payload(candidate)},
        status=201,
    )


@require_POST
def delete_intervention(
    request: HttpRequest,
    point_id: int,
    intervention_id: int,
) -> JsonResponse:
    try:
        intervention = SignalingIntervention.objects.get(
            pk=intervention_id,
            signaling_point_id=point_id,
        )
    except SignalingIntervention.DoesNotExist:
        return _api_not_found("Intervenção")
    intervention.delete()
    return JsonResponse(
        {"success": True, "deleted": True, "id": intervention_id}
    )


@require_POST
def update_intervention_condition(
    request: HttpRequest,
    point_id: int,
    intervention_id: int,
) -> JsonResponse:
    try:
        intervention = SignalingIntervention.objects.get(
            pk=intervention_id,
            signaling_point_id=point_id,
        )
    except SignalingIntervention.DoesNotExist:
        return _api_not_found("Intervenção")
    data = _read_json(request)
    if data is None:
        return JsonResponse(
            {"success": False, "error": "JSON inválido."},
            status=400,
        )

    intervention.condition = data.get("condition")
    try:
        intervention.full_clean()
    except ValidationError as error:
        return JsonResponse(
            {"success": False, "errors": _validation_errors(error)},
            status=400,
        )

    intervention.save(update_fields=["condition", "updated_at"])
    return JsonResponse(
        {"success": True, **_intervention_payload(intervention)}
    )


@require_POST
def update_intervention_notes(
    request: HttpRequest,
    point_id: int,
    intervention_id: int,
) -> JsonResponse:
    try:
        intervention = SignalingIntervention.objects.get(
            pk=intervention_id,
            signaling_point_id=point_id,
        )
    except SignalingIntervention.DoesNotExist:
        return _api_not_found("Intervenção")
    data = _read_json(request)
    if data is None:
        return JsonResponse(
            {"success": False, "error": "JSON inválido."},
            status=400,
        )

    notes = data.get("notes")
    if not isinstance(notes, str):
        return JsonResponse(
            {"success": False, "errors": {"notes": ["A observação deve ser um texto."]}},
            status=400,
        )

    intervention.notes = notes
    intervention.save(update_fields=["notes", "updated_at"])
    return JsonResponse(
        {"success": True, **_intervention_payload(intervention)}
    )
