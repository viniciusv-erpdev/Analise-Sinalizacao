"""Portable transport/error checks; not Linux/systemd homologation."""
from contextlib import nullcontext
import json
import struct
from unittest.mock import Mock, patch
from uuid import uuid4
from django.test import SimpleTestCase, override_settings
from django.core.management import call_command, CommandError
from signaling import report_active_dispatcher as service
from signaling.report_operations import execution_contract


class ActiveDispatchContractTests(SimpleTestCase):
    def setUp(self):
        self.db = Mock()
        self.db.candidate.return_value = dict(barrier_state="OPEN", other_unfinished=0, identity_count=0,
            launch_count=0, attempt_id=str(uuid4()), execution_id=str(uuid4()), generation=str(uuid4()),
            delivered=False, launch_state=None, admitted=True, state="ADMITTED", contract=execution_contract())
        self.delivery = {"fresh": True, "launch_id": str(uuid4()), "request_id": str(uuid4()), "generation": str(uuid4())}
        self.db.prepare.return_value = self.delivery

    def test_transport_only_after_committed_prepare(self):
        order = []
        self.db.prepare.side_effect = lambda *a, **kw: order.append("committed") or self.delivery
        send = lambda value: order.append("socket") or "JOB_OBSERVED"
        result = service.dispatch_once(self.db, release="a"*40, root="/opt/release", host_reader=Mock(), transport=send)
        self.assertEqual(order, ["committed", "socket"])
        self.assertEqual(result["outcome"], "JOB_OBSERVED")

    def test_prepare_exception_never_reaches_transport(self):
        self.db.prepare.side_effect = service.DispatchError("dispatch_database_state_unknown")
        send = Mock()
        with self.assertRaises(service.DispatchError):
            service.dispatch_once(self.db, release="a"*40, root="/opt/release", host_reader=Mock(), transport=send)
        send.assert_not_called()

    def test_all_uncertain_launches_and_prepared_deliveries_block_transport(self):
        send = Mock()
        for state, delivered in (("REQUESTED", True), ("UNCERTAIN", False),
                                  ("CONFIRMED", False), ("TERMINAL_OBSERVED", False)):
            self.db.candidate.return_value.update(launch_state=state, delivered=delivered)
            result = service.dispatch_once(self.db, release="a"*40, root="/opt/release", host_reader=Mock(), transport=send)
            self.assertEqual(result["outcome"], "DELIVERY_UNCERTAIN")
        send.assert_not_called()
        self.db.prepare.assert_not_called()

    def test_fixed_socket_root_peer_and_minimal_wire_payload(self):
        client = Mock()
        client.getsockopt.return_value = struct.pack("3i", 1234, 0, 0)
        client.send.side_effect = lambda raw: len(raw)
        client.recvmsg.return_value = (b'{"code":"JOB_OBSERVED","job_id":41}', [], 0, None)
        with patch.object(service.socket, "socket", return_value=nullcontext(client)), \
                patch.object(service.socket, "AF_UNIX", 1, create=True), \
                patch.object(service.socket, "SOCK_SEQPACKET", 5, create=True), \
                patch.object(service.socket, "SO_PEERCRED", 17, create=True), \
                patch.object(service.socket, "MSG_TRUNC", 32, create=True), \
                patch.object(service.socket, "MSG_CTRUNC", 8, create=True):
            self.assertEqual(service.send_request(self.delivery), "JOB_OBSERVED")
            client.connect.assert_called_with("/run/analise-report-launcher/control.sock")
            payload = json.loads(client.send.call_args.args[0])
            self.assertEqual(set(payload), {"protocol", "operation", "request_id", "launch_id", "expected_barrier_generation"})
            client.getsockopt.return_value = struct.pack("3i", 1234, 1001, 1001)
            client.send.reset_mock()
            with self.assertRaisesMessage(service.DispatchError, "dispatch_peer_not_root"):
                service.send_request(self.delivery)
            client.send.assert_not_called()

    @override_settings(REPORT_DISPATCH_ENABLED=True, REPORT_DISPATCH_DSN="secret DSN")
    def test_http_uid_cannot_invoke_active_command_and_no_secret_is_reflected(self):
        with patch("signaling.management.commands.dispatch_report_publication.require_dispatch_user",
                side_effect=service.DispatchError("dispatch_unix_identity_invalid")), \
                patch("signaling.management.commands.dispatch_report_publication.DispatchDatabase") as database:
            with self.assertRaisesMessage(CommandError, "dispatch_unix_identity_invalid"):
                call_command("dispatch_report_publication")
            database.assert_not_called()
