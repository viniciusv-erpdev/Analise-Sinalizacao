"""HTTP orchestration for the native Django public registration form."""
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import override
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .forms import RegistrationForm
from .services import register_analyst

logger = logging.getLogger(__name__)
UNAVAILABLE = "Não foi possível criar sua conta agora. Tente novamente mais tarde."


@sensitive_post_parameters("password1", "password2")
@never_cache
@require_http_methods(["GET", "POST"])
def register(request):
    next_url = request.POST.get("next", "") if request.method == "POST" else request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = ""
    # Keep native validator messages understandable without changing site language.
    with override("pt-br"):
        form = RegistrationForm(request.POST if request.method == "POST" else None)
        status = 200
        if not settings.REGISTRATION_ENABLED:
            return render(request, "registration/register.html", {
                "registration_available": False, "unavailable_message": UNAVAILABLE,
            }, status=403)
        if request.method == "POST" and form.is_valid():
            try:
                register_analyst(form)
            except ImproperlyConfigured:
                logger.error("Public registration unavailable: analista group is not provisioned.")
                form.add_error(None, UNAVAILABLE)
                status = 503
            except DatabaseError:
                # Do not log submitted data, passwords or SQL exception details.
                logger.error("Public registration failed during account persistence.")
                form.add_error(None, UNAVAILABLE)
                status = 503
            else:
                messages.success(request, "Conta criada com sucesso. Entre com seu usuário e senha.")
                login_url = reverse("login")
                if next_url:
                    login_url += "?" + urlencode({"next": next_url})
                return redirect(login_url)
        return render(request, "registration/register.html", {
            "form": form, "next": next_url, "registration_available": True,
        }, status=status)
