"""Typed, fixed API only. No systemctl/systemd-run subprocess or shell."""
import asyncio
import re
from .protocol import Rejected

SIGNATURES = {
    "Type": "s", "User": "s", "Group": "s", "WorkingDirectory": "s", "ExecStart": "a(sasb)",
    "EnvironmentFiles": "a(sb)", "Restart": "s", "KillMode": "s", "KillSignal": "i",
    "SendSIGKILL": "b", "TimeoutStopUSec": "t", "RuntimeMaxUSec": "t", "MemoryMax": "t",
    "TasksMax": "t", "OOMPolicy": "s", "Delegate": "b", "NoNewPrivileges": "b",
    "CapabilityBoundingSet": "t", "AmbientCapabilities": "t", "ProtectControlGroups": "b",
    "ProtectSystem": "s", "ProtectHome": "s", "PrivateTmp": "b", "PrivateDevices": "b",
    "RestrictSUIDSGID": "b", "RestrictNamespaces": "t", "UMask": "u", "ReadWritePaths": "as",
    "StandardOutput": "s", "StandardError": "s"}


class SystemManager:
    def preflight(self, unit, properties):
        if not re.fullmatch(r"rtsv-report-[a-f0-9]{32}\.service", unit) or set(properties) != set(SIGNATURES):
            raise Rejected("unit_policy_invalid")
        try:
            from dbus_next import Variant, Message
            values = []
            for key, value in properties.items():
                if key in ("ExecStart", "EnvironmentFiles"):
                    value = [list(row) for row in value]
                values.append([key, Variant(SIGNATURES[key], value)])
            return Message(destination="org.freedesktop.systemd1",
                path="/org/freedesktop/systemd1", interface="org.freedesktop.systemd1.Manager",
                member="StartTransientUnit", signature="ssa(sv)a(sa(sv))", body=[unit, "fail", values, []])
        except ImportError:
            raise Rejected("manager_dependency_unavailable") from None
        except Exception:
            raise Rejected("unit_policy_invalid") from None

    def start(self, unit, properties):
        self.preflight(unit, properties)
        return asyncio.run(asyncio.wait_for(self._start(unit, properties), timeout=5))

    async def _start(self, unit, properties):
        from dbus_next.aio import MessageBus
        from dbus_next import BusType, MessageType
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            reply = await bus.call(self.preflight(unit, properties))
            if reply.message_type == MessageType.ERROR or len(reply.body) != 1:
                raise Rejected("manager_result_unknown")
            job = re.fullmatch(r"/org/freedesktop/systemd1/job/([1-9][0-9]*)", reply.body[0])
            if not job:
                raise Rejected("manager_result_unknown")
            return int(job.group(1))
        finally:
            bus.disconnect()
