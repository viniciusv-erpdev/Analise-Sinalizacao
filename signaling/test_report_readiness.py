"""Portable readiness checks. Never executes a provisioning script."""
import json
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import zipfile

from django.test import SimpleTestCase
from scripts import report_release as release
from scripts.report_hml_plan import render
from signaling.report_ci_runner import NoSkipRunner
from report_launcher import catalog
from report_launcher.validation import digest
from signaling.test_pdf_conversion import fake_pdf
from signaling.pdf_conversion import validate_pdf


BASE = Path(__file__).resolve().parent.parent


class ReportReadinessTests(SimpleTestCase):
    def test_validator_is_required_and_shared_with_poc(self):
        pins = release.requirement_pins(BASE)
        self.assertEqual(pins["pypdf"], "6.21.3")
        self.assertEqual(release.requirement_pins(BASE, "requirements-pdf-poc.txt")["pypdf"], pins["pypdf"])
        import pypdf
        self.assertEqual(pypdf.__version__, pins["pypdf"])
        validate_pdf(fake_pdf())

    def test_default_flags_are_closed_in_http_and_dedicated_profile(self):
        with patch.dict(os.environ, {"DJANGO_DEBUG": "true"}, clear=True):
            main = runpy.run_path(str(BASE / "config/settings.py"))
            profile = runpy.run_path(str(BASE / "config/report_dispatch_settings.py"))
        for name in ("REPORT_FINALIZATION_ENABLED", "REPORT_ASYNC_PUBLICATION_ENABLED", "REPORT_ADMISSION_ENABLED",
                "REPORT_EXECUTOR_ENABLED", "REPORT_SYSTEMD_SUPERVISION_ENABLED", "REPORT_DISPATCH_ENABLED"):
            self.assertIs(main[name], False)
        self.assertIs(profile["REPORT_DISPATCH_ENABLED"], False)
        self.assertEqual(profile["DATABASES"]["default"]["ENGINE"], "django.db.backends.dummy")
        self.assertFalse(json.loads((BASE / "deploy/report-launcher-catalog.json.example").read_text())["enabled"])

    def test_no_skip_runner_rejects_skip_empty_and_errors(self):
        runner = NoSkipRunner(verbosity=0)
        for skipped, count, errors, expected in (([], 1, [], 0), ([("required", "missing")], 1, [], 1),
                ([], 0, [], 1), ([], 1, [("required", "failed")], 1)):
            result = Mock(skipped=skipped, testsRun=count, errors=errors, failures=[], unexpectedSuccesses=[])
            self.assertEqual(runner.suite_result(None, result), expected)
        class Required(unittest.TestCase):
            @unittest.skip("synthetic missing prerequisite")
            def runTest(self):
                pass
        actual = unittest.TestResult()
        unittest.TestSuite([Required()]).run(actual)
        self.assertEqual(runner.suite_result(None, actual), 1)

    def test_hml_plan_is_pure_guarded_and_does_not_create_credentials_or_memberships(self):
        sql = render("analise_hml", "report_hml")
        self.assertIn("current_database() <> 'analise_hml'", sql)
        self.assertIn('CREATE ROLE "report_hml_owner" NOLOGIN', sql)
        self.assertNotIn("PASSWORD", sql)
        self.assertNotIn("GRANT ALL", sql)
        self.assertNotIn("ALL TABLES", sql)
        self.assertNotIn("ALTER DEFAULT PRIVILEGES", sql)
        self.assertNotIn("ENABLE", sql)
        for target in ("postgres", "analise_dev", "analise_prod", "analise_hml';DROP DATABASE postgres"):
            with self.assertRaises(ValueError):
                render(target, "safe")
        with self.assertRaises(ValueError):
            render("analise_hml", "bad;role")

    def test_manifest_covers_inventory_and_uses_catalogue_hashes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("manage.py", ".venv/bin/python", ".venv/pyvenv.cfg", "requirements.txt", "requirements-pdf.txt",
                         "requirements.resolved.txt"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic")
            (root / ".venv/bin/python").chmod(0o755)
            hashes = release.write_manifest(root, "a"*40, {"prefix": str(root / ".venv")})
            raw = (root / "manifest.json").read_bytes()
            manifest = json.loads(raw)
            self.assertEqual(hashes["bundle_sha256"], digest(manifest["files"]))
            self.assertEqual({item["path"] for item in manifest["files"]},
                {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"})
            with self.assertRaises(ValueError):
                release.write_manifest(root, "a"*40, {})
            # Reuse production catalog tests' ownership substitution on Windows.
            # Kernel DAC is covered separately by the real Linux UID suite.
            self.assertEqual(manifest["contract"], catalog.CONTRACT)
            (root / "unexpected.env").write_bytes(b"not in inventory")
            self.assertNotIn("unexpected.env", {item["path"] for item in manifest["files"]})

    def test_inventory_refuses_checkout_and_secret_files(self):
        for name in ("db.sqlite3", ".env", ".env.hml"):
            with TemporaryDirectory() as directory:
                (Path(directory) / name).write_bytes(b"synthetic")
                with self.assertRaises(ValueError):
                    list(release.files(directory))

    def test_wheel_lock_pins_bytes_and_rejects_mixed_versions(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            def wheel(version):
                path = root / f"synthetic-{version}-py3-none-any.whl"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(f"synthetic-{version}.dist-info/METADATA", "Name: synthetic\nVersion: "+version+"\n")
            wheel("1.0")
            lock = release.wheel_lock(root)
            self.assertRegex(lock, r"synthetic==1\.0 --hash=sha256:[a-f0-9]{64}")
            self.assertEqual(lock, release.wheel_lock(root))
            wheel("2.0")
            with self.assertRaises(ValueError):
                release.wheel_lock(root)

    def test_runtime_audit_refuses_wrong_prefix_and_missing_validator(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".venv/bin").mkdir(parents=True)
            (root / ".venv/bin/python").write_bytes(b"synthetic")
            (root / ".venv/bin/python").chmod(0o755)
            (root / ".venv/pyvenv.cfg").write_text("include-system-site-packages = false\n")
            (root / "requirements.txt").write_text("pypdf==6.21.3\n")
            (root / "requirements.resolved.txt").write_text("pypdf==6.21.3 --hash=sha256:"+"a"*64+"\n")
            good = {"prefix": str(root / ".venv"), "base_prefix": str(root / "base"), "packages": {"pypdf": "6.21.3"}}
            for changed in ({"prefix": "/wrong/build/prefix"}, {"packages": {}}, {"packages": {"pypdf": "0.0"}}):
                with patch.object(release.subprocess, "run", return_value=Mock(stdout=json.dumps(good | changed))), \
                        self.assertRaises(ValueError):
                    release.runtime_metadata(root)
