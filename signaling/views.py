import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.http import require_POST

from signaling.forms import SignalingReportForm
from signaling.intervention_icons import get_intervention_icon_filename
from signaling.models import (
    MAX_SIGNALING_SEARCH_RADIUS_METERS,
    MIN_SIGNALING_SEARCH_RADIUS_METERS,
    SignalingIntervention,
    SignalingPoint,
)
from signaling.report_generator import (
    InvalidReportImage,
    build_accident_types_chart_data_uri,
    generate_signaling_report,
)
from signaling.report_filters import (
    InvalidIndividualReportFilters,
    parse_individual_report_filters,
)
from signaling.surveys import (
    ANALYSIS_SESSION_KEY,
    build_signaling_survey_from_items,
)


COORDINATE_PRECISION = Decimal("0.000001")
SEARCH_RADIUS_ERROR = (
    "O raio deve estar entre "
    f"{MIN_SIGNALING_SEARCH_RADIUS_METERS} e "
    f"{MAX_SIGNALING_SEARCH_RADIUS_METERS} metros."
)


def point_report(request: HttpRequest, point_id: int):
    point = get_object_or_404(
        SignalingPoint.objects.prefetch_related("interventions"),
        pk=point_id,
    )
    analysis_state = request.session.get(ANALYSIS_SESSION_KEY)
    survey = None
    filter_error = None
    report_filters = None
    if (
        isinstance(analysis_state, dict)
        and analysis_state.get("view_mode") == "individual"
        and isinstance(analysis_state.get("map_data"), list)
    ):
        accidents = analysis_state["map_data"]
        try:
            report_filters = parse_individual_report_filters(
                request.GET,
                accidents,
                analysis_state.get("analysis_id"),
            )
        except InvalidIndividualReportFilters as error:
            filter_error = str(error)
        else:
            filtered_accidents = report_filters.apply(accidents)
            survey = build_signaling_survey_from_items(
                point,
                filtered_accidents,
            )
            survey["filters"] = report_filters.presentation()

    form = (
        SignalingReportForm(request.POST, request.FILES)
        if request.method == "POST"
        else SignalingReportForm()
    )
    if request.method == "POST" and survey is not None and form.is_valid():
        try:
            report_buffer = generate_signaling_report(
                point,
                survey,
                form.cleaned_data,
                form.cleaned_data["photos"],
            )
        except InvalidReportImage as error:
            form.add_error("photos", str(error))
        else:
            filename = (
                f"relatorio_local_{point.id}_"
                f"{timezone.localdate().isoformat()}.docx"
            )
            return FileResponse(
                report_buffer,
                as_attachment=True,
                filename=filename,
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            )

    chart_data_uri = None
    if survey is not None:
        chart_data_uri = build_accident_types_chart_data_uri(survey)
        for intervention in survey["interventions"]:
            icon_filename = get_intervention_icon_filename(intervention["type"])
            intervention["icon_url"] = (
                static(f"icons/signaling/{icon_filename}")
                if icon_filename
                else None
            )

    return render(
        request,
        "signaling/report.html",
        {
            "point": point,
            "survey": survey,
            "form": form,
            "generated_on": timezone.localdate(),
            "chart_data_uri": chart_data_uri,
            "filter_error": filter_error,
        },
        status=400 if filter_error else 200,
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
        "search_radius_meters": point.search_radius_meters,
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
def update_point_search_radius(
    request: HttpRequest,
    point_id: int,
) -> JsonResponse:
    try:
        point = SignalingPoint.objects.get(pk=point_id)
    except SignalingPoint.DoesNotExist:
        return _api_not_found("Ponto de sinalizaÃ§Ã£o")
    data = _read_json(request)
    if data is None:
        return JsonResponse(
            {"success": False, "error": "JSON invÃ¡lido."},
            status=400,
        )

    value = data.get("search_radius_meters")
    try:
        radius = Decimal(str(value))
        if (
            isinstance(value, bool)
            or not radius.is_finite()
            or radius != radius.to_integral_value()
        ):
            raise ValueError
        point.search_radius_meters = int(radius)
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse(
            {
                "success": False,
                "error": f"{SEARCH_RADIUS_ERROR[:-1]} e ser um nÃºmero inteiro.",
            },
            status=400,
        )

    try:
        point.full_clean()
    except ValidationError:
        return JsonResponse(
            {
                "success": False,
                "error": SEARCH_RADIUS_ERROR,
            },
            status=400,
        )

    point.save(update_fields=["search_radius_meters", "updated_at"])
    return JsonResponse({
        "success": True,
        "id": point.id,
        "search_radius_meters": point.search_radius_meters,
    })


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
