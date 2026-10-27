"""Shared drafts: waypoint -> reservation -> draft locks, then revision check."""
from datetime import date
import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from signaling.authorization import REPORT, VIEW
from signaling.characterization import validate_report_text
from signaling.forms import PGTListField
from signaling.models import SignalingPoint, WaypointReportDraft, WaypointReservation
from signaling import reservations


TEXT_FIELDS = (
    "functional_classification", "geometric_configuration", "regulated_speed",
    "inspection_address", "study_reason", "study_objective", "inspector_name",
)
DATE_FIELDS = ("occurrence_date", "inspection_date")
DRAFT_FIELDS = (*TEXT_FIELDS, *DATE_FIELDS, "pgts")
MAX_REVISION = 9223372036854775807


class DraftRevisionConflict(Exception):
    def __init__(self, revision):
        self.revision = revision
        super().__init__("draft_revision_conflict")


def serialize_draft(point_id, draft):
    fields = {}
    for name in DRAFT_FIELDS:
        value = getattr(draft, name) if draft else (
            None if name in DATE_FIELDS else [] if name == "pgts" else ""
        )
        fields[name] = value.isoformat() if isinstance(value, date) else value
    return {
        "success": True, "point_id": point_id, "exists": draft is not None,
        "revision": draft.revision if draft else 0, "fields": fields,
        "updated_by": draft.updated_by_id if draft else None,
        "created_at": draft.created_at.isoformat() if draft else None,
        "updated_at": draft.updated_at.isoformat() if draft else None,
    }


def get_report_draft(*, point_id):
    if not SignalingPoint.objects.filter(pk=point_id).exists():
        raise reservations.ReservationWaypointNotFound()
    draft = WaypointReportDraft.objects.filter(signaling_point_id=point_id).first()
    return serialize_draft(point_id, draft)


def _validated_changes(changes):
    if not isinstance(changes, dict) or not changes or set(changes) - set(DRAFT_FIELDS):
        raise ValidationError({"fields": "Informe apenas campos editáveis do rascunho."})
    result, errors = {}, {}
    for name, value in changes.items():
        try:
            if name in TEXT_FIELDS:
                if not isinstance(value, str):
                    raise ValidationError("Informe um texto.")
                validate_report_text(value)
            elif name in DATE_FIELDS:
                if value is None or value == "":
                    value = None
                else:
                    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                        raise ValidationError("Informe uma data no formato AAAA-MM-DD.")
                    try:
                        value = date.fromisoformat(value)
                    except ValueError:
                        raise ValidationError("Informe uma data válida.") from None
            else:
                if not isinstance(value, list):
                    raise ValidationError("Informe uma lista de textos.")
                value = PGTListField(required=False).clean(value)
            result[name] = value
        except ValidationError as error:
            errors[name] = error.messages
    if errors:
        raise ValidationError(errors)
    return result


def save_report_draft(*, point_id, identity, credentials, expected_revision, changes):
    # Never authorize a write with an advisory status or a previously read draft.
    with reservations.validate_reservation(
        point_id=point_id, identity=identity, credentials=credentials,
    ) as point:
        reservation = WaypointReservation.objects.get(signaling_point=point)
        actor = get_user_model().objects.get(pk=reservation.user_id)
        if not actor.has_perms((VIEW, REPORT)):
            raise reservations.ReservationPermissionDenied()
        draft = WaypointReportDraft.objects.select_for_update().filter(
            signaling_point=point,
        ).first()
        if type(expected_revision) is not int or not 0 <= expected_revision <= MAX_REVISION:
            raise ValidationError({"expected_revision": "Informe uma revisão inteira não negativa."})
        revision = draft.revision if draft else 0
        if expected_revision != revision:
            raise DraftRevisionConflict(revision)
        if revision == MAX_REVISION:
            raise ValidationError({"expected_revision": "Limite de revisões atingido."})
        values = _validated_changes(changes)
        if draft is None:
            draft = WaypointReportDraft(signaling_point=point)
        for name, value in values.items():
            setattr(draft, name, value)
        draft.revision = revision + 1
        draft.updated_by = actor
        draft.full_clean()
        draft.save()
        return serialize_draft(point_id, draft)
