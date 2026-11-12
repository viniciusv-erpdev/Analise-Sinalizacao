"""Gunicorn configuration and actual HTTP parser policy (Linux CI)."""
import os
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GunicornConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.settings = runpy.run_path(str(ROOT / "deploy/gunicorn.conf.py"))

    def test_local_proxy_policy_and_nginx_contract(self):
        self.assertEqual(self.settings["forwarded_allow_ips"], "127.0.0.1,::1")
        self.assertEqual(self.settings["secure_scheme_headers"], {"X-FORWARDED-PROTO": "https"})
        for path in ("deploy/nginx.conf.example",
                     "deploy/ansible/roles/nginx_candidate/templates/site.conf.j2",
                     "deploy/tests/fixtures/production-http.conf"):
            with self.subTest(path=path):
                text = (ROOT / path).read_text()
                self.assertIn("proxy_pass http://127.0.0.1:8000;", text)
                self.assertIn("proxy_set_header X-Forwarded-Proto $scheme;", text)

    @unittest.skipIf(os.name == "nt", "Gunicorn requires a Unix environment")
    def test_real_parser_trusts_only_loopback_and_canonical_header(self):
        from gunicorn.config import Config
        from gunicorn.http.parser import RequestParser

        config = Config()
        for name in ("forwarded_allow_ips", "secure_scheme_headers"):
            config.set(name, self.settings[name])
        cases = (
            ("", "http"),
            ("X-Forwarded-Proto: http\r\n", "http"),
            ("X-Forwarded-Proto: https\r\n", "https"),
            ("X-Forwarded-SSL: on\r\n", "http"),
            ("X-Forwarded-Protocol: ssl\r\n", "http"),
            ("X-Forwarded-Proto: http\r\nX-Forwarded-SSL: on\r\nX-Forwarded-Protocol: ssl\r\n", "http"),
            ("X-Forwarded-Proto: https\r\nX-Forwarded-SSL: off\r\nX-Forwarded-Protocol: http\r\n", "https"),
        )
        for peer in ("127.0.0.1", "::1", "192.0.2.10"):
            for headers, loopback_scheme in cases:
                with self.subTest(peer=peer, headers=headers):
                    data = ("GET / HTTP/1.1\r\nHost: example.invalid\r\n" + headers + "\r\n").encode("ascii")
                    request = next(RequestParser(config, [data], (peer, 12345)))
                    self.assertEqual(request.scheme, "http" if peer == "192.0.2.10" else loopback_scheme)


if __name__ == "__main__":
    unittest.main()
