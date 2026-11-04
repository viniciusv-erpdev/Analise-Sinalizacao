"""Socket-activation entry point. Refuses non-Linux, non-root or manual binds."""
import json
import os
from pathlib import Path
import socket
import sys
import time
import stat

from .catalog import Catalog, _read
from .database import Database
from .protocol import receive, Rejected
from .service import Launcher, audit
from .systemd import SystemManager

CONFIG = "/etc/analise-report-launcher/catalog.json"
DSN = "/etc/analise-report-launcher/database.dsn"
SOCKET = "/run/analise-report-launcher/control.sock"


def main():
    if sys.platform != "linux" or os.geteuid() != 0 or len(sys.argv) != 1:
        raise Rejected("launcher_activation_required")
    if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise Rejected("launcher_activation_required")
    catalog = Catalog(CONFIG)
    import pwd
    dispatch, app = pwd.getpwnam("analise_dispatch"), pwd.getpwnam("analise_app")
    if (catalog.dispatcher_uid != dispatch.pw_uid or dispatch.pw_uid == app.pw_uid
            or dispatch.pw_uid <= 0 or app.pw_uid <= 0
            or dispatch.pw_gid in os.getgrouplist("analise_app", app.pw_gid)):
        raise Rejected("launcher_accounts_invalid")
    for path, mode in ((Path(SOCKET).parent, 0o750), (Path(SOCKET), 0o660)):
        info = path.lstat()
        if (info.st_uid != 0 or info.st_gid != dispatch.pw_gid or stat.S_IMODE(info.st_mode) != mode
                or stat.S_ISLNK(info.st_mode)):
            raise Rejected("launcher_socket_permissions_invalid")
    if Path(DSN).stat().st_mode & 0o077:
        raise Rejected("database_permissions_invalid")
    dsn = _read(DSN, limit=4096).decode("utf-8").strip()
    listener = socket.socket(fileno=3)
    if listener.family != socket.AF_UNIX or listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_SEQPACKET:
        raise Rejected("launcher_socket_invalid")
    if listener.getsockname() != SOCKET:
        raise Rejected("launcher_socket_invalid")
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    database = Database(dsn)
    database.verify_privileges()
    launcher = Launcher(database, catalog, SystemManager())
    window, requests = time.monotonic(), 0
    while True:
        connection, _ = listener.accept()
        with connection:
            peer, request = {"uid": -1}, None
            try:
                request, _ = receive(connection, catalog.dispatcher_uid, on_credentials=peer.update)
                now = time.monotonic()
                if now-window >= 1:
                    window, requests = now, 0
                requests += 1
                if requests > 8:
                    raise Rejected("rate_limited")
                result = launcher.handle(request, peer)
            except Rejected as error:
                result = {"code": str(error)}
                # Do not retain partial/untrusted payloads or kernel PID claims.
                audit(str(error), peer, request)
            except Exception:
                result = {"code": "launcher_unavailable"}
                audit("launcher_unavailable", peer, request)
            try:
                connection.send(json.dumps(result, sort_keys=True).encode("ascii"))
            except OSError:
                pass  # A response lost is not authorization to resend start.


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"event":"launcher_startup_refused"}', flush=True)
        sys.exit(1)
