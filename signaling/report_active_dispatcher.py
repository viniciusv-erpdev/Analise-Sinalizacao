"""One-shot nonprivileged dispatcher. No ORM, snapshots, files, or systemd API.

A committed delivery grants one socket send, NOT permission to start a unit.
No component here clears uncertainty, rotates fencing, or releases ownership.
"""
import json
from pathlib import Path
import re
import socket
import struct
import sys
from types import SimpleNamespace

from report_launcher.validation import CONTRACT

SOCKET = "/run/analise-report-launcher/control.sock"
FUNCTIONS = ("report_dispatch_candidate()", "report_dispatch_prepare(uuid,uuid,uuid,text,text,text,uuid)")


class DispatchError(Exception):
    pass


class DispatchDatabase:
    def __init__(self, dsn, *, connect=None):
        if not dsn:
            raise DispatchError("dispatch_database_not_configured")
        if connect is None:
            import psycopg
            connect = psycopg.connect
        self.dsn, self.connect = dsn, connect

    def _query(self, sql, parameters=()):
        # Connection context commits BEFORE handing a fresh delivery to the caller.
        # Lost commit acknowledgement therefore never permits a socket send.
        try:
            with self.connect(self.dsn, connect_timeout=5,
                    options="-c statement_timeout=5000 -c lock_timeout=1000") as db:
                with db.cursor() as cursor:
                    cursor.execute(sql, parameters)
                    value = cursor.fetchone()[0]
            return json.loads(value) if isinstance(value, str) else value
        except Exception:
            raise DispatchError("dispatch_database_state_unknown") from None

    def verify_privileges(self):
        safe = self._query("""SELECT current_user=session_user
          AND NOT (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls)
          AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid)
          AND NOT has_schema_privilege(current_user,'public','CREATE')
          AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p')
            AND (has_table_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
                 OR has_any_column_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE')))
          AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.proname LIKE 'report_launcher_%%'
              AND has_function_privilege(current_user,p.oid,'EXECUTE'))
          AND (SELECT count(*)=2 FROM pg_proc p JOIN pg_roles o ON o.oid=p.proowner
            JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.oid IN
             ('public.report_dispatch_candidate()'::regprocedure,
              'public.report_dispatch_prepare(uuid,uuid,uuid,text,text,text,uuid)'::regprocedure)
            AND p.prosecdef AND NOT o.rolcanlogin AND NOT o.rolsuper
            AND p.proconfig=ARRAY['search_path=pg_catalog']
            AND has_function_privilege(current_user,p.oid,'EXECUTE'))
          FROM pg_roles r WHERE r.rolname=current_user""")
        if safe is not True:
            raise DispatchError("dispatch_database_privileges_unsafe")

    def candidate(self):
        return self._query("SELECT public.report_dispatch_candidate()")

    def prepare(self, candidate, *, release, root, host):
        return self._query("SELECT public.report_dispatch_prepare(%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s::uuid)",
            (candidate["attempt_id"], candidate["execution_id"], candidate["generation"],
             release, root, host.host_id, str(host.boot_id)))


def send_request(delivery):
    """Fixed root-owned socket, kernel-authenticated peer, bounded single packet."""
    from report_launcher.protocol import decode
    packet = {"protocol": 1, "operation": "start", "request_id": str(delivery["request_id"]),
              "launch_id": str(delivery["launch_id"]),
              "expected_barrier_generation": str(delivery["generation"])}
    raw = json.dumps(packet).encode()
    decode(raw)
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as client:
        client.settimeout(10)
        client.connect(SOCKET)
        _, uid, _ = struct.unpack("3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != 0:
            raise DispatchError("dispatch_peer_not_root")
        if client.send(raw) != len(raw):
            raise DispatchError("dispatch_delivery_unknown")
        response, _, flags, _ = client.recvmsg(4096)
        if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
            raise DispatchError("dispatch_response_invalid")
        result = json.loads(response)
        if not isinstance(result, dict) or result.get("code") not in {
                "JOB_OBSERVED", "ALREADY_CONSUMED", "UNCERTAIN"}:
            raise DispatchError("dispatch_response_unknown")
        return result["code"]  # Never reflect arbitrary remote fields into logs.


def dispatch_once(db, *, release, root, host_reader, transport=send_request):
    """Revalidation happens inside prepare and again at launcher consumption."""
    candidate = db.candidate()
    if candidate["barrier_state"] != "OPEN":
        return {"outcome": "MAINTENANCE"}
    if (candidate["other_unfinished"] or candidate["identity_count"] > 1
            or candidate["launch_count"] > 1):
        return {"outcome": "INCONSISTENT"}
    if not candidate["attempt_id"]:
        return {"outcome": "UNCERTAIN" if candidate["identity_count"] or candidate["launch_count"] else "NO_ADMISSION"}
    if candidate["delivered"] or candidate["launch_state"] in ("UNCERTAIN", "CONFIRMED", "TERMINAL_OBSERVED"):
        return {"outcome": "DELIVERY_UNCERTAIN"}
    if not candidate["admitted"] or candidate["state"] != "ADMITTED":
        return {"outcome": "EXECUTION_IN_PROGRESS" if candidate["state"] in ("PROCESSING", "STORING") else "UNCERTAIN"}
    if candidate["contract"] != CONTRACT:
        return {"outcome": "INCOMPATIBLE"}
    if (not re.fullmatch(r"[a-f0-9]{40,64}", release) or not root.startswith("/")
            or root == "/" or ".." in Path(root).parts):
        raise DispatchError("dispatch_configuration_invalid")
    delivery = db.prepare(candidate, release=release, root=root, host=host_reader())
    if not delivery["fresh"]:
        return {"outcome": "DELIVERY_UNCERTAIN"}
    try:
        outcome = transport(delivery)
    except Exception:
        # The immutable delivery was committed first. No resend even if the
        # launcher never received it, rejected it, or its response disappeared.
        outcome = "DELIVERY_UNCERTAIN"
    return {"outcome": outcome, "launch_id": str(delivery["launch_id"])}


def require_dispatch_user():
    import os
    if sys.platform != "linux":
        raise DispatchError("dispatch_linux_required")
    import pwd
    try:
        dispatcher, app = pwd.getpwnam("analise_dispatch"), pwd.getpwnam("analise_app")
        if (os.getuid() != dispatcher.pw_uid or os.geteuid() != dispatcher.pw_uid
                or dispatcher.pw_uid <= 0 or app.pw_uid <= 0 or dispatcher.pw_uid == app.pw_uid
                or os.getgid() != dispatcher.pw_gid or os.getegid() != dispatcher.pw_gid
                or set(os.getgroups()) - {dispatcher.pw_gid}
                or dispatcher.pw_gid in os.getgrouplist(app.pw_name, app.pw_gid)):
            raise DispatchError("dispatch_unix_identity_invalid")
    except KeyError:
        raise DispatchError("dispatch_unix_identity_missing") from None


def host_identity():
    from report_launcher.service import host_identity as read_host
    from report_launcher.protocol import Rejected
    try:
        host, boot = read_host()
    except Rejected:
        raise DispatchError("dispatch_host_identity_unavailable") from None
    return SimpleNamespace(host_id=host, boot_id=boot)
