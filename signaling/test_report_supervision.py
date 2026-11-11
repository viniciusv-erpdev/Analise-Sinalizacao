"""Contract fixtures are not live systemd attestation. No unit is ever started."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from signaling import report_systemd_runtime as runtime
from signaling.report_finalization import FinalizationError


HOST = runtime.HostIdentity("a" * 32, uuid4())
RELEASE = "b" * 40


def observations(identity):
    properties = {"InvocationID": uuid4().hex, "ControlGroup": f"/system.slice/{identity.unit_name}",
        "MainPID": "1234", "ActiveState": "active", "Type": "exec", "KillMode": "control-group",
        "Delegate": "no", "User": identity.service_user, "NoNewPrivileges": "yes",
        "ProtectControlGroups": "yes", "Restart": "no"}
    return dict(host=runtime.HostIdentity(identity.host_id, identity.boot_id), properties=properties,
        pid=1234, uid=1001, start_ticks=123456, invocation=properties["InvocationID"],
        cgroup=properties["ControlGroup"], cgroup_inode=12345, capabilities=0,
        no_new_privileges=True, cgroup_writable=False)


@override_settings(REPORT_EXECUTOR_RELEASE_ID=RELEASE)
class SystemdRuntimeContractTests(SimpleTestCase):
    def setUp(self):
        key = uuid4()
        self.identity = SimpleNamespace(pk=key, unit_name=f"rtsv-report-{key.hex}.service", host_id=HOST.host_id,
            boot_id=HOST.boot_id, release_id=RELEASE, release_root=str(Path(settings.BASE_DIR).resolve()), service_user="rtsv-report")

    def test_valid_fixture_binds_identity_but_has_no_termination_claim(self):
        result = runtime.validate_runtime(self.identity, **observations(self.identity))
        self.assertEqual(result.unit_name, self.identity.unit_name)
        self.assertFalse(hasattr(result, "terminated"))

    def test_environment_invocation_alone_or_pid_alone_cannot_pass(self):
        for changes in ({"invocation": uuid4().hex}, {"pid": 9999}, {"host": runtime.HostIdentity("c"*32, HOST.boot_id)},
                {"host": runtime.HostIdentity(HOST.host_id, uuid4())}, {"cgroup": "/other"}, {"uid": 0},
                {"capabilities": 1}, {"cgroup_writable": True}, {"no_new_privileges": False}):
            with self.subTest(changes=list(changes)), self.assertRaises(FinalizationError):
                runtime.validate_runtime(self.identity, **(observations(self.identity) | changes))

    def test_inactive_missing_or_weakened_manager_properties_are_refused(self):
        for key, value in (("ActiveState", "inactive"), ("ActiveState", "deactivating"), ("InvocationID", ""),
                ("Delegate", "yes"), ("ProtectControlGroups", "no"), ("KillMode", "process"),
                ("Restart", "on-failure"), ("Type", "oneshot"), ("User", "root"), ("MainPID", "0")):
            data = observations(self.identity)
            data["properties"][key] = value
            with self.subTest(property=key), self.assertRaises(FinalizationError):
                runtime.validate_runtime(self.identity, **data)

    def test_manager_adapter_is_read_only_fixed_argv_and_sanitized_environment(self):
        result = SimpleNamespace(returncode=0, stdout=b"ActiveState=active\nMainPID=1234\n")
        with patch.object(runtime.subprocess, "run", return_value=result) as run:
            runtime.manager_properties(self.identity.unit_name)
        args, kwargs = run.call_args
        self.assertEqual(args[0][:4], ["/usr/bin/systemctl", "--system", "show", self.identity.unit_name])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(set(kwargs["env"]), {"PATH", "LANG", "SYSTEMD_PAGER", "SYSTEMD_COLORS"})
        self.assertEqual(kwargs["timeout"], 5)

    def test_missing_unit_or_lost_history_is_unknown_not_termination(self):
        with patch.object(runtime.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout=b"")):
            with self.assertRaisesMessage(FinalizationError, "supervision_manager_unavailable"):
                runtime.manager_properties(self.identity.unit_name)

    def test_arbitrary_unit_or_shell_string_never_reaches_subprocess(self):
        with patch.object(runtime.subprocess, "run") as run:
            with self.assertRaises(FinalizationError):
                runtime.manager_properties("anything.service; reboot")
        run.assert_not_called()
