import pandas as pd

from analysis.map_data import (
    INDIVIDUAL_FILTER_CATEGORIES,
    build_individual_accident_item,
)
from analysis.spatial import haversine_distance_meters
from signaling.models import SignalingIntervention, SignalingPoint


ANALYSIS_SESSION_KEY = "accident_analysis_state"

POINT_STATUS_LABELS = {
    SignalingPoint.Status.OK: "Completa",
    SignalingPoint.Status.INCOMPLETE: "Incompleta",
    SignalingPoint.Status.ABSENT: "Ausente",
}

INTERVENTION_CONDITION_LABELS = {
    SignalingIntervention.Condition.OK: "Adequada",
    SignalingIntervention.Condition.ABSENT: "Inadequada",
}


def build_signaling_survey(
    signaling_point: SignalingPoint,
    accidents: pd.DataFrame,
) -> dict[str, object]:
    """Associa sinistros individuais normalizados ao ponto informado."""
    return build_signaling_survey_from_items(
        signaling_point,
        [build_individual_accident_item(row) for _, row in accidents.iterrows()],
    )


def build_signaling_survey_from_items(
    signaling_point: SignalingPoint,
    accidents: list[dict[str, object]],
) -> dict[str, object]:
    """Monta sob demanda um levantamento a partir do payload individual enxuto."""
    nearby_accidents = []
    category_labels = dict(INDIVIDUAL_FILTER_CATEGORIES)
    accidents_by_type = {label: 0 for label in category_labels.values()}
    fatal_count = 0
    non_fatal_count = 0

    point_latitude = float(signaling_point.latitude)
    point_longitude = float(signaling_point.longitude)
    radius_meters = signaling_point.search_radius_meters

    for item in accidents:
        distance = haversine_distance_meters(
            point_latitude,
            point_longitude,
            float(item["latitude"]),
            float(item["longitude"]),
        )
        if distance > radius_meters:
            continue

        accident = dict(item)
        accident["distance_meters"] = round(distance, 2)
        nearby_accidents.append(accident)

        category_label = category_labels[accident["category"]]
        accidents_by_type[category_label] += 1
        if item["record_type"] == "SINISTRO FATAL":
            fatal_count += 1
        elif item["record_type"] == "SINISTRO NAO FATAL":
            non_fatal_count += 1

    interventions = [
        {
            "id": intervention.id,
            "type": intervention.type,
            "type_label": intervention.get_type_display(),
            "condition": intervention.condition,
            "condition_label": INTERVENTION_CONDITION_LABELS[
                intervention.condition
            ],
            "notes": intervention.notes,
        }
        for intervention in signaling_point.interventions.order_by("id")
    ]

    return {
        "signaling_point_id": signaling_point.id,
        "radius_meters": radius_meters,
        "status": {
            "value": signaling_point.status,
            "label": POINT_STATUS_LABELS[signaling_point.status],
        },
        "total_accidents": len(nearby_accidents),
        "summary": {
            "fatal": fatal_count,
            "non_fatal": non_fatal_count,
            "by_type": accidents_by_type,
        },
        "interventions": interventions,
        "accidents": nearby_accidents,
    }
