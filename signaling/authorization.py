"""Access policy only; exclusive reservations are a separate future check."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views.csrf import csrf_failure as default_csrf_failure

VIEW = "signaling.view_signalingpoint"
ADD = "signaling.add_signalingpoint"
CHANGE = "signaling.change_signalingpoint"
DELETE = "signaling.delete_signalingpoint"
REPORT = "signaling.generate_signaling_report"


def signaling_access(*permissions, api=True, write_permissions=()):
    """Require view plus operation permissions before reading domain objects."""
    def decorator(view):
        @wraps(view)
        def checked(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if api:
                    return JsonResponse({
                        "success": False, "code": "authentication_required",
                        "error": "Sua sessão expirou ou você não entrou. Entre novamente.",
                    }, status=401)
                return login_required(view)(request, *args, **kwargs)
            required = (VIEW, *permissions)
            if request.method != "GET":
                required += tuple(write_permissions)
            if not request.user.has_perms(required):
                if api:
                    return JsonResponse({
                        "success": False, "code": "permission_denied",
                        "error": "Você não tem permissão para esta operação.",
                    }, status=403)
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return checked
    return decorator


def csrf_failure(request, reason=""):
    # Only signaling JSON endpoints; HTML forms keep Django's standard response.
    match = request.resolver_match
    if match and "signaling" in match.namespaces and match.url_name != "point-report":
        return JsonResponse({
            "success": False, "code": "csrf_failed",
            "error": "A sessão ou o formulário expirou. Recarregue a página antes de tentar novamente.",
        }, status=403)
    return default_csrf_failure(request, reason=reason)
