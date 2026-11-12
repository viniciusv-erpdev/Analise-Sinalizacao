"""Offline rendering contracts; optional real Nginx syntax check for HTTP only."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "deploy/ansible/roles/nginx_candidate"


class NginxTemplateTests(unittest.TestCase):
    def setUp(self):
        self.values = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.values.update(nginx_static_root="/srv/example/staticfiles", nginx_max_upload_size="25m")
        env = Environment(loader=FileSystemLoader(ROLE / "templates"), undefined=StrictUndefined,
                          trim_blocks=True)
        env.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(pattern, replacement, value)
        self.template = env.get_template("site.conf.j2")

    def render(self, **changes):
        return self.template.render(**{**self.values, **changes})

    def test_http_matches_existing_example(self):
        old = (ROOT / "deploy/nginx.conf.example").read_text()
        for source, target in (("<SERVER_NAME>", "_"), ("<STATIC_ROOT>", self.values["nginx_static_root"]),
                               ("<MAX_UPLOAD_SIZE>", "25m")):
            old = old.replace(source, target)
        normalize = lambda text: " ".join(re.sub(r"#.*", "", text).split())
        self.assertEqual(normalize(old), normalize(self.render()))

    def production_values(self):
        return yaml.safe_load((ROOT / "deploy/ansible/examples/production-http.yml").read_text(encoding="utf-8-sig"))

    @staticmethod
    def normalized(text):
        return " ".join(re.sub(r"#.*", "", text).split())

    def test_http_matches_reported_production(self):
        fixture = (ROOT / "deploy/tests/fixtures/production-http.conf").read_text()
        text = self.render(**self.production_values())
        self.assertEqual(self.normalized(fixture), self.normalized(text))
        self.assertNotIn("listen 443", text)
        self.assertNotIn("ssl_certificate", text)
        self.assertNotIn("return 308", text)

    def test_production_http_and_https_preserve_same_application_block(self):
        values = self.production_values()
        baseline = self.render(**values)
        values.update(nginx_https_enabled=True, nginx_tls_certificate="/external/fullchain.pem",
                      nginx_tls_certificate_key="/external/private.key")
        text = self.render(**values)
        # Both top-level blocks must match production after removing TLS-only directives.
        blocks = re.split(r"(?m)^server \{", text)[1:]
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            block = re.sub(r"(?m)^\s*ssl_\w+ .*;\s*$", "", block)
            block = block.replace("listen 443 ssl;", "listen 80;")
            self.assertEqual(self.normalized("server {" + block), self.normalized(baseline))
        self.assertNotIn("return 308", text)
        self.assertNotIn("return 301", text)

    def test_future_hostname_and_protocol_header_contract(self):
        values = self.production_values()
        values.update(nginx_https_enabled=True, nginx_server_name="hml.example.invalid",
                      nginx_tls_certificate="/external/fullchain.pem",
                      nginx_tls_certificate_key="/external/private.key")
        text = self.render(**values)
        self.assertNotIn("172.28.240.99", text)
        self.assertEqual(text.count("server_name hml.example.invalid;"), 2)
        self.assertEqual(text.count("proxy_set_header Host $http_host;"), 2)
        self.assertEqual(text.count("proxy_set_header X-Forwarded-Proto $scheme;"), 2)
        self.assertNotIn("$http_x_forwarded_proto", text)
        self.assertEqual(text.count("proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;"), 2)

    def test_tls_and_redirect_matrix(self):
        for redirect in (False, True):
            with self.subTest(redirect=redirect):
                text = self.render(nginx_https_enabled=True, nginx_server_name="hml.example.invalid",
                                   nginx_tls_certificate="/external/fullchain.pem",
                                   nginx_tls_certificate_key="/external/private.key",
                                   nginx_http_redirect_https=redirect)
                self.assertIn("listen 443 ssl;", text)
                self.assertIn("ssl_protocols TLSv1.2 TLSv1.3;", text)
                self.assertEqual(text.count("proxy_pass http://127.0.0.1:8000;"), 1 if redirect else 2)
                self.assertEqual("return 308 https://hml.example.invalid$request_uri;" in text, redirect)
                self.assertNotIn("https://$host", text)
                self.assertEqual(text.count("proxy_set_header X-Forwarded-Proto $scheme;"), 1 if redirect else 2)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible not installed")
    def test_ansible_role_validates_inputs_and_renders(self):
        with tempfile.TemporaryDirectory() as directory:
            values = {**self.values, "nginx_candidate_path": directory + "/candidate.conf"}
            cases = [({}, True), ({"nginx_https_enabled": True}, False),
                     ({"nginx_http_redirect_https": True}, False),
                     ({"nginx_https_enabled": "false"}, False),
                     ({"nginx_max_upload_size": "0"}, False),
                     ({"nginx_forwarded_for_mode": "invalid"}, False),
                     ({"nginx_forwarded_for_mode": "append"}, True),
                     ({"nginx_candidate_path": "/etc/nginx/sites-enabled/example"}, False),
                     ({"nginx_https_enabled": True, "nginx_server_name": "hml.example.invalid",
                       "nginx_tls_certificate": "/external/fullchain.pem",
                       "nginx_tls_certificate_key": "/external/private.key"}, True)]
            for changes, expected in cases:
                with self.subTest(changes=changes):
                    play = Path(directory) / "test.yml"
                    play.write_text(yaml.safe_dump([{
                        "hosts": "localhost", "connection": "local", "gather_facts": False,
                        "vars": {**values, **changes}, "roles": [str(ROLE)],
                    }]))
                    result = subprocess.run(["ansible-playbook", "-i", "localhost,", str(play)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)
                    if expected:
                        self.assertTrue(Path(values["nginx_candidate_path"]).is_file())

    @unittest.skipUnless(shutil.which("nginx"), "Nginx not installed")
    def test_http_nginx_syntax(self):
        for values in ({}, self.production_values()):
            with self.subTest(values=values):
                self.check_http_nginx_syntax(self.render(**values))

    def check_http_nginx_syntax(self, rendered):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nginx.conf"
            path.write_text("pid " + directory + "/nginx.pid;\nerror_log stderr;\nevents {}\nhttp {\naccess_log off;\n"
                            + rendered + "\n}\n")
            subprocess.run([shutil.which("nginx"), "-t", "-p", directory + "/", "-c", str(path)], check=True)


if __name__ == "__main__":
    unittest.main()

