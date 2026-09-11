from django.db.models import Prefetch

from signaling.models import SignalingIntervention, SignalingPoint


def get_signaling_map_data() -> list[dict[str, object]]:
    return [
        {
            "id": point.id,
            "latitude": float(point.latitude),
            "longitude": float(point.longitude),
            "status": point.status,
            "search_radius_meters": point.search_radius_meters,
            "interventions": [
                {
                    "id": intervention.id,
                    "type": intervention.type,
                    "condition": intervention.condition,
                    "notes": intervention.notes,
                }
                for intervention in point.interventions.all()
            ],
        }
        for point in SignalingPoint.objects.only(
            "id", "latitude", "longitude", "status", "search_radius_meters"
        ).prefetch_related(
            Prefetch(
                "interventions",
                queryset=SignalingIntervention.objects.only(
                    "id", "signaling_point_id", "type", "condition", "notes"
                ).order_by("id"),
            )
        ).order_by("id")
    ]
