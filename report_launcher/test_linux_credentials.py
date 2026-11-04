"""REAL UIDs/DAC/SCM_CREDENTIALS. Run standalone as root in disposable Linux.

Never run this module through manage.py or on the production VM. No useradd,
systemd, DB, or report storage access; uses existing daemon/nobody identities.
"""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import signal
import unittest

from .protocol import receive, Rejected
from .test_launcher import wire
from .catalog import trusted

LINUX_ROOT = sys.platform == "linux" and getattr(os, "geteuid", lambda: -1)() == 0 and "django" not in sys.modules


@unittest.skipUnless(LINUX_ROOT, "Requires standalone root in disposable Linux; no Django imports")
class RealUnixCredentialTests(unittest.TestCase):
    def setUp(self):
        import pwd
        self.dispatch = pwd.getpwnam("daemon")
        self.http = pwd.getpwnam("nobody")
        self.assertNotEqual(self.dispatch.pw_uid, self.http.pw_uid)
        self.assertGreater(self.dispatch.pw_uid, 0)
        self.assertGreater(self.http.pw_uid, 0)
        self.temp = tempfile.TemporaryDirectory(prefix="report-launcher-tests-", dir="/run")
        self.addCleanup(self.temp.cleanup)
        self.children = set()
        self.addCleanup(self.cleanup_children)

    def cleanup_children(self):
        # Only children forked by this test, never arbitrary system processes.
        for pid in tuple(self.children):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
            self.children.remove(pid)

    def child(self, account, operation):
        pid = os.fork()
        if pid == 0:
            try:
                os.setgroups([])
                os.setgid(account.pw_gid)
                os.setuid(account.pw_uid)
                if (os.getuid(), os.geteuid(), os.getgid(), os.getegid(), os.getgroups()) != (
                        account.pw_uid, account.pw_uid, account.pw_gid, account.pw_gid, []):
                    raise RuntimeError("Child did not drop Unix privileges")
                operation()
            except BaseException:
                os._exit(1)
            os._exit(0)
        self.children.add(pid)
        return pid

    def wait_ok(self, pid):
        deadline = time.monotonic() + 10
        while True:
            found, status = os.waitpid(pid, os.WNOHANG)
            if found:
                self.children.remove(pid)
                break
            if time.monotonic() >= deadline:
                self.fail("Test child did not finish within 10 seconds")
            time.sleep(0.01)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)

    def test_filesystem_socket_permissions_different_users_and_real_credentials(self):
        directory = Path(self.temp.name)
        directory.chmod(0o750)
        os.chown(directory, 0, self.dispatch.pw_gid)
        path = str(directory / "control.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            listener.bind(path)
            os.chown(path, 0, self.dispatch.pw_gid)
            os.chmod(path, 0o660)
            listener.listen(1)
            listener.settimeout(5)
            def send():
                with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as client:
                    client.settimeout(5)
                    client.connect(path)
                    client.send(json.dumps(wire()).encode())
                    if client.recv(20) != b"ok":
                        raise RuntimeError()
            pid = self.child(self.dispatch, send)
            connection, _ = listener.accept()
            with connection:
                _, peer = receive(connection, self.dispatch.pw_uid)
                self.assertEqual(peer, {"pid": pid, "uid": self.dispatch.pw_uid,
                                       "gid": self.dispatch.pw_gid})
                connection.send(b"ok")
            self.wait_ok(pid)
            def denied():
                with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as client:
                    try:
                        client.connect(path)
                    except PermissionError:
                        return
                    raise RuntimeError("Unauthorized UID reached socket")
            self.wait_ok(self.child(self.http, denied))

    def test_same_connected_descriptor_reused_by_other_uid_is_rejected(self):
        receiver, sender = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with receiver, sender:
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            def send():
                sender.send(json.dumps(wire()).encode())
            pid = self.child(self.dispatch, send)
            _, peer = receive(receiver, self.dispatch.pw_uid)
            self.assertEqual(peer, {"pid": pid, "uid": self.dispatch.pw_uid,
                                   "gid": self.dispatch.pw_gid})
            self.wait_ok(pid)
            # Descriptor inheritance is the same authority problem as FD passing.
            pid = self.child(self.http, send)
            with self.assertRaisesRegex(Rejected, "peer_forbidden"):
                receive(receiver, self.dispatch.pw_uid)
            self.wait_ok(pid)

    def test_private_0700_0600_files_are_inaccessible_to_dispatch_uid(self):
        directory = Path(self.temp.name)
        directory.chmod(0o755)
        private = directory / "private"
        private.mkdir(mode=0o700)
        secret = private / "fixture.pdf"
        secret.write_bytes(b"synthetic private bytes")
        secret.chmod(0o600)
        os.chown(secret, self.http.pw_uid, self.http.pw_gid)
        os.chown(private, self.http.pw_uid, self.http.pw_gid)
        self.wait_ok(self.child(self.http, lambda: self.assertEqual(
            secret.read_bytes(), b"synthetic private bytes")))
        def denied():
            try:
                secret.read_bytes()
            except PermissionError:
                return
            raise RuntimeError("Dispatcher read private file")
        self.wait_ok(self.child(self.dispatch, denied))

    def test_real_root_ownership_and_writable_catalog_rejected(self):
        path = Path(self.temp.name) / "catalog.json"
        path.write_text("{}")
        path.chmod(0o600)
        self.assertEqual(trusted(path), path)
        path.chmod(0o660)
        with self.assertRaises(Rejected):
            trusted(path)
        path.chmod(0o600)
        os.chown(path, self.dispatch.pw_uid, self.dispatch.pw_gid)
        with self.assertRaises(Rejected):
            trusted(path)
