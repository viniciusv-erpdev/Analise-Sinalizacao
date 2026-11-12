from unittest import TestCase

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.test import override_settings

from config.proxy import proxy_settings


class ProxySettingsTests(TestCase):
    def test_defaults_preserve_http(self):
        options = proxy_settings({})
        self.assertEqual(options, {
            "SECURE_PROXY_SSL_HEADER": None,
            "SESSION_COOKIE_SECURE": False,
            "CSRF_COOKIE_SECURE": False,
        })
        with override_settings(**options):
            request = HttpRequest()
            request.META["HTTP_X_FORWARDED_PROTO"] = "https"
            self.assertFalse(request.is_secure())

    def test_trusted_proxy_recognizes_actual_scheme(self):
        with override_settings(**proxy_settings({"DJANGO_TRUST_PROXY_HTTPS": "true"})):
            request = HttpRequest()
            for scheme, expected in (("https", True), ("http", False)):
                request.META["HTTP_X_FORWARDED_PROTO"] = scheme
                self.assertEqual(request.is_secure(), expected)

    def test_cookies_are_independent(self):
        options = proxy_settings({"DJANGO_SESSION_COOKIE_SECURE": "yes"})
        self.assertTrue(options["SESSION_COOKIE_SECURE"])
        self.assertFalse(options["CSRF_COOKIE_SECURE"])
        self.assertIsNone(options["SECURE_PROXY_SSL_HEADER"])

    def test_trust_requires_header_and_does_not_enable_redirect_or_secure_cookies(self):
        options = proxy_settings({"DJANGO_TRUST_PROXY_HTTPS": "true"})
        with override_settings(**options):
            request = HttpRequest()
            request.META["REMOTE_ADDR"] = "127.0.0.1"
            self.assertFalse(request.is_secure())
        self.assertFalse(options["SESSION_COOKIE_SECURE"])
        self.assertFalse(options["CSRF_COOKIE_SECURE"])
        self.assertNotIn("SECURE_SSL_REDIRECT", options)

    def test_header_trust_is_not_a_proxy_ip_allowlist(self):
        # Documents the boundary: exposing Gunicorn would permit spoofing.
        with override_settings(**proxy_settings({"DJANGO_TRUST_PROXY_HTTPS": "true"})):
            request = HttpRequest()
            request.META.update(REMOTE_ADDR="192.0.2.10", HTTP_X_FORWARDED_PROTO="https")
            self.assertTrue(request.is_secure())

    def test_invalid_boolean_fails_closed(self):
        for name in ("DJANGO_TRUST_PROXY_HTTPS", "DJANGO_SESSION_COOKIE_SECURE", "DJANGO_CSRF_COOKIE_SECURE"):
            with self.subTest(name=name), self.assertRaises(ImproperlyConfigured):
                proxy_settings({name: "tru"})
