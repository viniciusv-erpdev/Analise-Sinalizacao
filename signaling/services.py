from django.db.models import Prefetch

from signaling.models import SignalingIntervention, SignalingPoint


def get_signaling_map_data() -> list[dict[str, object]]:
    return [
        {
            "id": point.id,
            "latitude": float(point.latitude),
            "longitude": float(point.longitude),
            "status": point.status,
            "interventions": [
                {
                    "id": intervention.id,
                    "type": intervention.type,
                    "condition": intervention.condition,
                }
                for intervention in point.interventions.all()
            ],
        }
        for point in SignalingPoint.objects.only(
            "id", "latitude", "longitude", "status"
        ).prefetch_related(
            Prefetch(
                "interventions",
                queryset=SignalingIntervention.objects.only(
                    "id", "signaling_point_id", "type", "condition"
                ).order_by("id"),
            )
        ).order_by("id")
    ]
