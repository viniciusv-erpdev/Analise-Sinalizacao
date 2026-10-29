"""Private finalization API, no archive downloads or frontend integration."""
from functools import wraps
import json
from uuid import UUID

from django.http import JsonResponse
from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.debug import sensitive_variables

from signaling.authorization import REPORT, signaling_access
from signaling import report_finalization as service, reservations
from signaling.reservation_http import credentials, identity, private, failure, ReservationHeadersMissing
from signaling.report_filters import InvalidIndividualReportFilters
from signaling.report_snapshots import prepare_photos
from signaling.surveys import ANALYSIS_SESSION_KEY


def api(view):
    @wraps(view)
    def checked(request, *args, **kwargs):
        try:
            return private(view(request, *args, **kwargs))
        except (reservations.ReservationError, ReservationHeadersMissing) as error:
            return failure(error)
        except service.FinalizationError as error:
            result = {"success": False, "code": error.code,
                      "error": "Finalization unavailable; inspect attempt state before retrying."}
            if error.attempt:
                error.attempt.refresh_from_db()
                result["attempt"] = service.describe(error.attempt)
            return private(JsonResponse(result, status=error.status))
        except ImproperlyConfigured:
            import logging
            logging.getLogger(__name__).exception(
                "Configuração inválida durante a finalização oficial"
            )
            return private(JsonResponse(
                {"success": False, "code": "finalization_configuration_invalid"},
                status=503,
          ))
        except (ValidationError, InvalidIndividualReportFilters, ValueError, TypeError) as error:
            result = {"success": False, "code": "invalid_finalization_payload"}
            if isinstance(error, ValidationError):
                result["errors"] = error.message_dict if hasattr(error, "message_dict") else error.messages
            return private(JsonResponse(result, status=400))
    return checked


def _payload(request, *, retry=False):
    allowed = set() if retry else {"idempotency_key", "expected_revision"}
    if request.content_type == "application/json":
        data = json.loads(request.body)
    elif request.content_type == "multipart/form-data":
        if set(request.FILES) - {"photos"} or any(len(request.POST.getlist(key)) != 1 for key in request.POST):
            raise ValueError
        data = request.POST.dict()
        data.pop("csrfmiddlewaretoken", None)
        if not retry:
            revision = data.get("expected_revision", "")
            if not revision.isascii() or not revision.isdecimal():
                raise ValueError
            data["expected_revision"] = int(revision)
    else:
        raise ValueError
    if not isinstance(data, dict) or set(data) != allowed:
        raise ValueError
    return data, prepare_photos(request.FILES.getlist("photos"))


def response(attempt, *, created=False):
    status = 201 if created and attempt.state == "FINALIZED" else 200 if attempt.state == "FINALIZED" else 202
    if attempt.state in ("FAILED", "INTERRUPTED"):
        status = 409  # Explicit retry only. POST replay never re-executes side effects.
    return JsonResponse(service.describe(attempt), status=status)


@api
@require_POST
@signaling_access(REPORT, service.FINALIZE)
@sensitive_variables()
def finalize_report(request, point_id):
    service.require_enabled()
    data, photos = _payload(request)
    proof = credentials(request)
    attempt = service.finalize(point_id=point_id, user_id=request.user.pk,
        identity=identity(request), credentials=proof, key=UUID(data["idempotency_key"]),
        expected_revision=data["expected_revision"], parameters=request.GET,
        analysis_state=request.session.get(ANALYSIS_SESSION_KEY), photos=photos)
    return response(attempt, created=True)


@api
@require_GET
@signaling_access(REPORT, service.FINALIZE)
def finalization_status(request, attempt_id):
    service.require_enabled()
    return JsonResponse(service.describe(service.get_attempt(attempt_id, request.user.pk)))


@api
@require_POST
@signaling_access(REPORT, service.FINALIZE)
@sensitive_variables()
def retry_finalization(request, attempt_id):
    service.require_enabled()
    _, photos = _payload(request, retry=True)
    return response(service.retry(attempt_id=attempt_id, user_id=request.user.pk,
        identity=identity(request), credentials=credentials(request), photos=photos))
