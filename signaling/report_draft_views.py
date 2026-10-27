"""JSON-only draft API; no changes to document generation or the visual form."""
import json

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from signaling.authorization import REPORT, signaling_access
from signaling.report_drafts import DraftRevisionConflict, get_report_draft, save_report_draft
from signaling.reservation_http import credentials, identity
from signaling.reservation_views import guard


@require_http_methods(["GET", "POST"])
@signaling_access(REPORT)
@guard
def report_draft(request, point_id):
    if request.method == "GET":
        return JsonResponse(get_report_draft(point_id=point_id))
    # Read proof before parsing content; missing/invalid acquisitions never write.
    proof = credentials(request)
    try:
        if request.content_type != "application/json":
            raise ValueError
        data = json.loads(request.body)
        if not isinstance(data, dict) or set(data) != {"expected_revision", "fields"}:
            raise ValueError
    except (ValueError, TypeError, UnicodeDecodeError):
        return JsonResponse({
            "success": False, "code": "invalid_draft_payload",
            "error": "Envie JSON com expected_revision e fields, sem arquivos ou outros dados.",
        }, status=400)
    try:
        result = save_report_draft(
            point_id=point_id, identity=identity(request), credentials=proof,
            expected_revision=data["expected_revision"], changes=data["fields"],
        )
    except DraftRevisionConflict as error:
        return JsonResponse({
            "success": False, "code": "draft_revision_conflict",
            "error": "O rascunho foi alterado. Recarregue antes de salvar.",
            "revision": error.revision,
        }, status=409)
    except ValidationError as error:
        return JsonResponse({
            "success": False, "code": "invalid_draft_fields",
            "error": "Revise os campos do rascunho.", "errors": error.message_dict,
        }, status=400)
    return JsonResponse(result)
