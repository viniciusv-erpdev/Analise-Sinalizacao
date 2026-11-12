"""Opt-in header trust; isolation of Gunicorn is enforced outside Django.

SECURE_PROXY_SSL_HEADER does not check REMOTE_ADDR. Nginx must overwrite the
header and untrusted clients must not be able to reach Gunicorn directly.
"""
from django.core.exceptions import ImproperlyConfigured


def proxy_settings(environ):
    result = {}
    for variable, setting in (
        ("DJANGO_TRUST_PROXY_HTTPS", "SECURE_PROXY_SSL_HEADER"),
        ("DJANGO_SESSION_COOKIE_SECURE", "SESSION_COOKIE_SECURE"),
        ("DJANGO_CSRF_COOKIE_SECURE", "CSRF_COOKIE_SECURE"),
    ):
        value = environ.get(variable, "false").strip().lower()
        if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ImproperlyConfigured(f"{variable} must be a boolean.")
        enabled = value in {"true", "1", "yes", "on"}
        result[setting] = (
            ("HTTP_X_FORWARDED_PROTO", "https") if enabled else None
        ) if setting == "SECURE_PROXY_SSL_HEADER" else enabled
    return result
