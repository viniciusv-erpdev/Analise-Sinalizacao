from signaling.models import SignalingIntervention


INTERVENTION_ICON_FILES = {
    SignalingIntervention.Type.TRAFFIC_LIGHT: "traffic-light.svg",
    SignalingIntervention.Type.PEDESTRIAN_CROSSING: "pedestrians-crossing-icon.svg",
    SignalingIntervention.Type.MINI_ROUNDABOUT: "rotatory-icon.svg",
    SignalingIntervention.Type.RIGHT_OF_WAY_REVERSAL: "reversal-right-of-way-icon.svg",
    SignalingIntervention.Type.TRAFFIC_FLOW_CHANGE: "traffic-change-icon.svg",
    SignalingIntervention.Type.PEDESTRIAN_REFUGE: "pedestrian-refuges-icon.svg",
    SignalingIntervention.Type.NO_PARKING: "no-parking-icon.svg",
    SignalingIntervention.Type.GEOMETRY_ADJUSTMENT: "geometry-icon.svg",
    SignalingIntervention.Type.SPEED_REDUCTION: "speedometer-icon.svg",
    SignalingIntervention.Type.VERTICAL_HORIZONTAL_SIGNALING: "signaling-icon.svg",
    SignalingIntervention.Type.LOW_VISIBILITY: "signal-low-vision.svg",
    SignalingIntervention.Type.R1: "signal-stop-icon.svg",
    SignalingIntervention.Type.STREET_LIGHTING: "street-ligth-icon.svg",
    SignalingIntervention.Type.SPEED_BUMP: "signal-speed-bump.svg",
    SignalingIntervention.Type.R5A: "R-5a-icon.svg",
    SignalingIntervention.Type.R5B: "R-5b-icon.svg",
    SignalingIntervention.Type.R4A: "R-4a-icon.svg",
    SignalingIntervention.Type.R24A: "R-24a-icon.svg",
    SignalingIntervention.Type.R6C: "R-6c-icon.svg",
    SignalingIntervention.Type.R6A: "R-6a-icon.svg",
    SignalingIntervention.Type.RAISED_CROSSWALK: "raised-crosswalk-icon.svg",
}


def get_intervention_icon_filename(intervention_type: str) -> str | None:
    return INTERVENTION_ICON_FILES.get(intervention_type)
