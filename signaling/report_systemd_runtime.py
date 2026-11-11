"""Linux/system-manager observation only. Never starts/stops units or kills PIDs.

These observations bind startup identity. They do NOT attest group termination.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID

from django.conf import settings
from signaling.report_finalization import FinalizationError


@dataclass(frozen=True)
class HostIdentity:
    host_id: str
    boot_id: UUID


@dataclass(frozen=True)
class RuntimeIdentity:
    host: HostIdentity
    unit_name: str
    invocation_id: UUID
    cgroup_path: str
    cgroup_inode: int
    main_pid: int
    process_start_ticks: int


def host_identity():
    if sys.platform != "linux":
        raise FinalizationError("supervision_linux_required", 503)
    try:
        host = Path("/etc/machine-id").read_text().strip()
        boot = UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip())
        if not re.fullmatch(r"[0-9a-f]{32}", host) or int(host, 16) == 0 or boot.int == 0:
            raise ValueError
        return HostIdentity(host, boot)
    except (OSError, ValueError):
        raise FinalizationError("supervision_host_identity_unavailable", 503) from None


PROPERTIES = ("InvocationID", "ControlGroup", "MainPID", "ActiveState", "Type", "KillMode",
              "Delegate", "User", "NoNewPrivileges", "ProtectControlGroups", "Restart")


def manager_properties(unit):
    # Unit names are exclusively derived from persisted random UUIDs.
    if not re.fullmatch(r"rtsv-report-[0-9a-f]{32}\.service", unit):
        raise FinalizationError("supervision_unit_invalid")
    try:
        result = subprocess.run(["/usr/bin/systemctl", "--system", "show", unit, "--no-pager",
            "--property=" + ",".join(PROPERTIES)], shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, cwd="/",
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0"})
        if result.returncode or len(result.stdout) > 16384:
            raise ValueError
        return dict(line.split("=", 1) for line in result.stdout.decode("utf-8").splitlines() if "=" in line)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # Missing, inaccessible and history lost are UNKNOWN, never proof of death.
        raise FinalizationError("supervision_manager_unavailable", 503) from None


def validate_runtime(identity, host, properties, *, pid, uid, start_ticks, invocation,
                     cgroup, cgroup_inode, capabilities, no_new_privileges, cgroup_writable):
    """Pure validation shared by real capture and fixture-based contract tests."""
    expected_group = f"/system.slice/{identity.unit_name}"
    expected = {"Type": "exec", "KillMode": "control-group", "Delegate": "no",
                "User": identity.service_user, "NoNewPrivileges": "yes",
                "ProtectControlGroups": "yes", "Restart": "no"}
    try:
        runtime_invocation = UUID(invocation)
        manager_invocation = UUID(properties.get("InvocationID", ""))
        valid = (host.host_id == identity.host_id and host.boot_id == identity.boot_id
            and identity.unit_name == f"rtsv-report-{identity.pk.hex}.service"
            and runtime_invocation.int != 0 and runtime_invocation == manager_invocation
            and pid > 0 and uid > 0 and start_ticks > 0 and cgroup_inode > 0
            and int(properties.get("MainPID", "0")) == pid
            and cgroup == expected_group == properties.get("ControlGroup")
            and properties.get("ActiveState") in ("activating", "active")
            and all(properties.get(key) == value for key, value in expected.items())
            and capabilities == 0 and no_new_privileges and not cgroup_writable
            and identity.release_root == str(Path(settings.BASE_DIR).resolve())
            and identity.release_id == settings.REPORT_EXECUTOR_RELEASE_ID)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise FinalizationError("supervision_runtime_mismatch", 503)
    return RuntimeIdentity(host, identity.unit_name, runtime_invocation, cgroup, cgroup_inode, pid, start_ticks)


def capture(identity):
    host = host_identity()
    try:
        status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
        groups = [line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::")]
        if len(groups) != 1:
            raise ValueError
        group = groups[0]
        if group != f"/system.slice/{identity.unit_name}":
            raise ValueError
        directory = Path("/sys/fs/cgroup") / group.lstrip("/")
        # cgroup v2 and host-visible hierarchy are required. No private cgroup namespace.
        if not (directory / "cgroup.events").is_file():
            raise ValueError
        process_stat = Path("/proc/self/stat").read_text()
        start_ticks = int(process_stat[process_stat.rfind(")") + 2:].split()[19])
        return validate_runtime(identity, host, manager_properties(identity.unit_name),
            pid=os.getpid(), uid=os.geteuid(), start_ticks=start_ticks,
            invocation=os.environ.get("INVOCATION_ID", ""), cgroup=group,
            cgroup_inode=directory.stat().st_ino, capabilities=int(status["CapEff"].strip(), 16),
            no_new_privileges=status["NoNewPrivs"].strip() == "1",
            cgroup_writable=os.access(directory / "cgroup.procs", os.W_OK))
    except (OSError, ValueError, KeyError, IndexError):
        raise FinalizationError("supervision_runtime_unavailable", 503) from None
