"""Portable isolated tests. Real kernel/UID tests are in test_linux_credentials."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import struct
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import Mock, MagicMock, patch
from uuid import uuid4

from . import protocol, catalog, validation
from .database import Database
from .service import Launcher
from .systemd import SystemManager, SIGNATURES


def wire(**changes):
    return {"protocol": 1, "operation": "start", "request_id": str(uuid4()), "launch_id": str(uuid4()),
        "expected_barrier_generation": str(uuid4())} | changes


class ProtocolTests(unittest.TestCase):
    def test_strict_shape_no_executable_input(self):
        value = wire()
        self.assertEqual(protocol.decode(json.dumps(value).encode()), value)
        for extra in ("command", "argv", "environment", "unit", "path", "properties", "user", "dispatch_id"):
            with self.assertRaises(protocol.Rejected):
                protocol.decode(json.dumps(value | {extra: "arbitrary"}).encode())

    def test_duplicate_keys_invalid_ids_depth_and_size(self):
        for packet in (b'{"protocol":1,"protocol":1}', b"x"*4097, b"["*2000, b'{"protocol":NaN}'):
            with self.assertRaises(protocol.Rejected):
                protocol.decode(packet)
        with self.assertRaises(protocol.Rejected):
            protocol.decode(json.dumps(wire(request_id=";reboot")).encode())
        self.assertEqual(protocol.decode(json.dumps(wire(expected_barrier_generation=str(__import__('uuid').UUID(int=0)))).encode())["protocol"], 1)

    def test_simulated_credentials_require_per_message_exact_uid(self):
        # Linux ABI constants are simulated on Windows; this is NOT a kernel test.
        with patch.object(socket, "SCM_CREDENTIALS", 2, create=True), patch.object(socket, "SCM_RIGHTS", 1, create=True), \
                patch.object(socket, "MSG_TRUNC", 32, create=True), patch.object(socket, "MSG_CTRUNC", 8, create=True):
            credential = [(socket.SOL_SOCKET, 2, struct.pack("3i", 123, 2001, 2001))]
            self.assertEqual(protocol.authenticate(credential, 0, 2001)["uid"], 2001)
            for ancillary, flags in (([], 0), (credential, 32), (credential*2, 0)):
                with self.assertRaises(protocol.Rejected):
                    protocol.authenticate(ancillary, flags, 2001)
            with self.assertRaises(protocol.Rejected):
                protocol.authenticate(credential, 0, 2002)

    def test_no_django_or_subprocess_import_in_standalone_package(self):
        for path in Path(__file__).parent.glob("*.py"):
            if path.name.startswith("test_"):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                self.assertFalse(any(name.split(".")[0] in {"django", "signaling", "config", "subprocess"} for name in names))

    def test_fresh_isolated_interpreter_imports_no_django(self):
        source = str(Path(__file__).resolve().parent.parent)
        script = ("import sys; sys.path.insert(0,"+repr(source)+"); import report_launcher.__main__; "
                  "print(any(n.split('.')[0] in {'django','signaling','config'} for n in sys.modules))")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), b"False")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.db, self.catalog, self.manager = Mock(), Mock(), Mock()
        self.catalog.dispatcher_uid = 2001
        self.db.status.return_value = {"state": "REQUESTED", "consumed": False}
        self.db.envelope.return_value = {"identity": {"release_id": "a"*40}}
        self.db.consume.return_value = {"fresh": True}
        self.catalog.validate.return_value = {"root": "/releases/a", "python": "/releases/a/.venv/bin/python",
            "environment_file": "/etc/executor.env", "private_report_root": "/var/lib/analise/reports"}
        self.manager.start.return_value = 41
        self.audit = Mock()
        self.service = Launcher(self.db, self.catalog, self.manager,
            host_reader=lambda: ("b"*32, uuid4()), audit_writer=self.audit)
        self.request, self.peer = wire(), {"uid": 2001}
        validator = patch("report_launcher.service.validate_envelope", return_value=("rtsv-report-"+"a"*32+".service", str(uuid4())))
        validator.start()
        self.addCleanup(validator.stop)

    def test_one_start_after_commit_and_fixed_properties(self):
        order = []
        self.db.consume.side_effect = lambda *args: order.append("committed") or {"fresh": True}
        self.manager.start.side_effect = lambda *args: order.append("systemd") or 41
        self.assertEqual(self.service.handle(self.request, self.peer)["code"], "JOB_OBSERVED")
        self.assertEqual(order, ["committed", "systemd"])
        properties = self.manager.start.call_args.args[1]
        self.assertEqual(set(properties), set(SIGNATURES))
        self.assertEqual(properties["User"], "analise_app")
        self.assertEqual(properties["KillMode"], "control-group")
        self.assertFalse(properties["Delegate"])
        self.assertEqual(properties["CapabilityBoundingSet"], 0)

    def test_replay_and_old_uncertain_never_call_manager(self):
        for status in ({"state": "UNCERTAIN", "consumed": True}, {"state": "UNCERTAIN", "consumed": False}):
            self.db.status.return_value = status
            self.service.handle(self.request, self.peer)
        self.db.consume.assert_not_called()
        self.manager.start.assert_not_called()

    def test_commit_ack_loss_prevents_external_call(self):
        self.db.consume.side_effect = protocol.Rejected("database_state_unknown")
        with self.assertRaises(protocol.Rejected):
            self.service.handle(self.request, self.peer)
        self.manager.start.assert_not_called()

    def test_missing_manager_dependency_does_not_consume_authorization(self):
        self.manager.preflight.side_effect = protocol.Rejected("manager_dependency_unavailable")
        with self.assertRaises(protocol.Rejected):
            self.service.handle(self.request, self.peer)
        self.db.consume.assert_not_called()
        self.manager.start.assert_not_called()

    def test_manager_timeout_existing_unit_and_storage_ack_leave_uncertain(self):
        for error in (TimeoutError(), RuntimeError("existing")):
            self.manager.start.side_effect = error
            self.assertEqual(self.service.handle(self.request, self.peer)["code"], "UNCERTAIN")
        self.manager.start.side_effect = None
        self.db.record_job.side_effect = protocol.Rejected("database_state_unknown")
        self.assertEqual(self.service.handle(self.request, self.peer)["code"], "UNCERTAIN")

    def test_second_authority_gets_no_grant(self):
        self.db.consume.return_value = {"fresh": False}
        self.assertEqual(self.service.handle(self.request, self.peer)["code"], "ALREADY_CONSUMED")
        self.manager.start.assert_not_called()

    def test_peer_catalog_rejection_and_status_do_not_start(self):
        with self.assertRaises(protocol.Rejected):
            self.service.handle(self.request, {"uid": 2002})
        self.catalog.validate.side_effect = protocol.Rejected("manifest_mismatch")
        with self.assertRaises(protocol.Rejected):
            self.service.handle(self.request, self.peer)
        self.db.consume.assert_not_called()
        self.request["operation"] = "status"
        self.assertEqual(self.service.handle(self.request, self.peer)["code"], "STATUS")
        self.manager.start.assert_not_called()

    def test_typed_manager_rejects_arbitrary_names_before_dbus_import(self):
        with self.assertRaises(protocol.Rejected):
            SystemManager().start("gunicorn.service", {})


class CatalogTests(unittest.TestCase):
    def test_inventory_hashes_extra_files_paths_and_disabled(self):
        # Ownership checks are mocked here; Linux tests validate real Unix DAC.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("manage.py", ".venv/bin/python", ".venv/pyvenv.cfg"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic")
            (root / ".venv/bin/python").chmod(0o755)
            environment = root.parent / (root.name+".env")
            environment.write_text("DJANGO_DB_BACKEND=postgresql\nDJANGO_DEBUG=false\n"
                "REPORT_EXECUTOR_RELEASE_ID="+"a"*40+"\nREPORT_EXECUTOR_SYSTEMD_USER=analise_app\n"
                "REPORT_PRIVATE_ROOT=/var/lib/analise/reports\nREPORT_EXECUTOR_ENABLED=true\n"
                "REPORT_SYSTEMD_SUPERVISION_ENABLED=true\n", encoding="utf-8")
            self.addCleanup(environment.unlink, missing_ok=True)
            environment.chmod(0o600)
            files = [{"path": name, "sha256": hashlib.sha256(b"synthetic").hexdigest()}
                     for name in ("manage.py", ".venv/bin/python", ".venv/pyvenv.cfg")]
            manifest = {"protocol": 1, "release_id": "a"*40, "contract": validation.CONTRACT, "files": files}
            raw = validation.canonical(manifest)
            (root / "manifest.json").write_bytes(raw)
            data = {"protocol": 1, "enabled": True, "dispatcher_uid": 2001,
                "private_report_root": "/var/lib/analise/reports", "releases": {"a"*40: {
                "root": str(root), "environment_file": str(environment),
                "manifest_sha256": hashlib.sha256(raw).hexdigest(), "bundle_sha256": validation.digest(files)}}}
            instance = catalog.Catalog.__new__(catalog.Catalog)
            instance.data = data
            with patch.object(catalog, "trusted", side_effect=lambda path, **kw: Path(path)), \
                    patch.object(catalog, "_read", side_effect=lambda path, **kw: Path(path).read_bytes()):
                # Windows does not represent Unix owner-only modes or executable bits.
                original_stat = Path.stat
                def info(path, *args, **kwargs):
                    actual = original_stat(path, *args, **kwargs)
                    if path == environment or path == root / ".venv/bin/python":
                        return type("Info", (), {"st_mode": 0o100600 if path == environment else 0o100755})()
                    return actual
                with patch.object(Path, "stat", info):
                    self.assertEqual(instance.validate("a"*40)["release_id"], "a"*40)
                    (root / "manage.py").write_bytes(b"changed")
                    with self.assertRaises(protocol.Rejected):
                        instance.validate("a"*40)
                    (root / "manage.py").write_bytes(b"synthetic")
                    (root / "extra.py").write_bytes(b"unlisted")
                    with self.assertRaises(protocol.Rejected):
                        instance.validate("a"*40)
                    (root / "extra.py").unlink()
                    data["enabled"] = False
                    with self.assertRaises(protocol.Rejected):
                        instance.validate("a"*40)


class DatabaseAckTests(unittest.TestCase):
    def test_context_commit_failure_never_returns_ticket(self):
        context = MagicMock()
        context.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = [{"fresh": True}]
        context.__exit__.side_effect = RuntimeError("lost ACK")
        db = Database("not-used", connect=Mock(return_value=context))
        with self.assertRaises(protocol.Rejected):
            db._query("SELECT 1", ())
        context.__exit__.assert_called_once()
