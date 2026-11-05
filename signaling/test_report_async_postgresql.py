"""Isolated PostgreSQL + HTTP/SQL integration. Never call systemd or render PDFs."""
import json
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from django.conf import settings
from django.core.management import call_command, CommandError
from django.db import connection, transaction, DatabaseError
from django.test import Client, override_settings
from django.urls import reverse

from signaling import report_operations as operations, report_finalization as legacy
from signaling import report_admission as admission, report_supervision as supervision
from signaling import report_executor as executor, report_systemd_runtime as runtime
from signaling.models import (ReportLaunch as Launch, ReportDispatchDelivery as Delivery,
    ReportExecutionIdentity as Identity, ReportReleaseAuthorization as Release,
    ReportFinalizationAttempt as Attempt, ReportAnnualCounter, WaypointReservation,
    ReportLauncherReceipt as Receipt, ReportOperationalEvent as Event, ReportArtifact,
    ReportPublicationSlot as Slot)
from signaling.report_active_dispatcher import DispatchDatabase, DispatchError, dispatch_once, FUNCTIONS
from signaling.test_report_operations_postgresql import OperationsFixture
from signaling.test_report_finalization_postgresql import ReportFinalizationPostgreSQLTests as HttpFixture
from signaling.test_report_supervision import HOST, RELEASE
from signaling.surveys import ANALYSIS_SESSION_KEY
from signaling.test_support import authorize

ROOT = "/opt/analise/releases/" + RELEASE


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL")
class AsyncPublicationPostgreSQLTests(OperationsFixture):
    headers = HttpFixture.headers
    client_for_thread = HttpFixture.client_for_thread
    post = HttpFixture.post
    retry_http = HttpFixture.retry_http

    def setUp(self):
        super().setUp()
        config = override_settings(REPORT_FINALIZATION_ENABLED=True, REPORT_ASYNC_PUBLICATION_ENABLED=True)
        config.enable()
        self.addCleanup(config.disable)
        self.key = uuid4()
        session = self.client.session
        session[ANALYSIS_SESSION_KEY] = {"view_mode": "individual", "map_data": []}
        session.save()
        Release.objects.create(release_id=RELEASE, bundle_sha256="1"*64, manifest_sha256="2"*64,
            execution_contract=operations.execution_contract(), approved_by=uuid4())

    def database(self):
        connection.ensure_connection()
        return DispatchDatabase(connection.connection.info.dsn)

    def prepare(self, db=None):
        db = db or self.database()
        return db.prepare(db.candidate(), release=RELEASE, root=ROOT, host=HOST)

    def dispatch(self, transport=None, db=None):
        return dispatch_once(db or self.database(), release=RELEASE, root=ROOT,
                             host_reader=lambda: HOST, transport=transport or Mock(return_value="JOB_OBSERVED"))

    def test_http_admits_and_returns_owner_status_without_rendering(self):
        with patch.object(legacy, "_execute", side_effect=AssertionError("No HTTP conversion")):
            result = self.post()
        self.assertEqual(result.status_code, 202)
        self.assertTrue(result.json()["accepted"])
        self.assertEqual(Attempt.objects.get().state, "ADMITTED")
        self.assertFalse(Launch.objects.exists())
        response = self.client.get(result["Location"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["publication_phase"], "AWAITING_DISPATCH")
        self.assertIn("no-store", response["Cache-Control"])
        for forbidden in ("snapshot", "execution_id", "request_id", "release_root", "identity_id"):
            self.assertNotIn(forbidden, response.json())

    def test_auth_permission_owner_csrf_and_reservation_are_enforced(self):
        url = reverse("signaling:finalize-report", args=[self.point.pk])
        self.assertEqual(Client().post(url).status_code, 401)
        other = Client()
        authorize(other, ("view_signalingpoint",))
        self.assertEqual(other.post(url).status_code, 403)
        csrf = Client(enforce_csrf_checks=True)
        csrf.cookies = self.client.cookies
        self.assertEqual(csrf.post(url, {}, content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(url, {"idempotency_key": str(self.key), "expected_revision": 1},
            content_type="application/json").status_code, 428)
        result = self.post()
        other = Client()
        authorize(other, self.reservation_permissions)
        self.assertEqual(other.get(result["Location"]).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(result["Location"]).status_code, 401)

    def test_http_replay_revision_and_fingerprint(self):
        self.assertEqual(self.post(expected_revision=9).status_code, 409)
        first = self.post()
        self.assertEqual(self.post().json()["attempt_id"], first.json()["attempt_id"])
        self.assertEqual(self.post(expected_revision=2).json()["code"], "idempotency_key_conflict")
        self.assertEqual(Attempt.objects.count(), 1)
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)

    def test_concurrent_http_distinct_intentions_have_only_one_number(self):
        results = self.race(lambda: self.post(key=uuid4()), lambda: self.post(key=uuid4()))
        self.assertEqual(sorted(result.status_code for result in results), [202, 409])
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)
        self.assertEqual(Attempt.objects.count(), 1)

    def test_concurrent_same_http_intention_never_duplicates(self):
        results = self.race(self.post, self.post)
        self.assertTrue(any(result.status_code == 202 for result in results))
        self.assertEqual(Attempt.objects.count(), 1)
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)

    def test_closed_reservation_does_not_revoke_admission_status_or_dispatch(self):
        result = self.post()
        WaypointReservation.objects.filter(signaling_point=self.point).delete()
        self.assertEqual(self.post().status_code, 202)  # key replay, no new capture
        self.assertEqual(self.client.get(result["Location"]).status_code, 200)
        self.assertEqual(self.dispatch()["outcome"], "JOB_OBSERVED")
        attempt = Attempt.objects.get()
        self.assertEqual(self.retry_http(attempt).status_code, 202)
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)

    def test_durable_delivery_precedes_transport_and_is_never_resent(self):
        self.post()
        def send(delivery):
            self.assertTrue(Delivery.objects.filter(pk=delivery["request_id"]).exists())
            self.assertEqual(Launch.objects.get().state, "REQUESTED")
            self.assertFalse(Receipt.objects.exists())
            raise TimeoutError("lost response")
        self.assertEqual(self.dispatch(send)["outcome"], "DELIVERY_UNCERTAIN")
        connection.close()  # simulated HTTP/dispatcher restart
        send_again = Mock()
        self.assertEqual(self.dispatch(send_again)["outcome"], "DELIVERY_UNCERTAIN")
        send_again.assert_not_called()
        attempt = Attempt.objects.get()
        result = self.client.get(reverse("signaling:report-finalization-status", args=[attempt.pk]))
        self.assertTrue(result.json()["requires_reconciliation"])
        self.assertEqual(Delivery.objects.count(), 1)

    def test_two_dispatchers_send_only_once(self):
        self.post()
        db = self.database()
        sent = Mock(return_value="JOB_OBSERVED")
        def run():
            try:
                return self.dispatch(sent, db)
            except DispatchError:
                return {"outcome": "BUSY"}
        self.race(run, run)
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(Identity.objects.count(), 1)
        self.assertEqual(Launch.objects.count(), 1)
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertEqual(Event.objects.filter(kind="DISPATCH_DELIVERY_PREPARED").count(), 1)

    def test_prepare_and_deploy_race_never_authorizes_unsafe_deploy(self):
        self.post()
        db = self.database()
        def prepare():
            try:
                return self.prepare(db)
            except DispatchError:
                return "blocked"
        self.race(prepare, lambda: self.move("DRAINING"))
        self.assertEqual(self.dispatch()["outcome"], "MAINTENANCE")
        with self.assertRaisesMessage(Exception, "deployment_not_quiescent"):
            self.move("DEPLOYING")

    def test_admission_and_drain_race_is_serialized(self):
        results = self.race(self.post, lambda: self.move("DRAINING"))
        response = next(value for value in results if hasattr(value, "status_code"))
        self.assertIn(response.status_code, (202, 409, 503))
        self.assertEqual(self.post().status_code, 202 if Attempt.objects.exists() else 503)

    def test_stale_generation_slot_release_and_contract_refuse_without_partial_writes(self):
        self.post()
        db = self.database()
        candidate = db.candidate()
        self.move("DRAINING")
        self.move("OPEN")
        with self.assertRaises(DispatchError):
            db.prepare(candidate, release=RELEASE, root=ROOT, host=HOST)
        for changed in ({"execution_id": str(uuid4())}, {"attempt_id": str(uuid4())}):
            with self.assertRaises(DispatchError):
                db.prepare(db.candidate() | changed, release=RELEASE, root=ROOT, host=HOST)
        with self.assertRaises(DispatchError):
            db.prepare(db.candidate(), release="c"*40, root=ROOT, host=HOST)
        Attempt.objects.update(execution_contract={"admission": 9})
        self.assertEqual(self.dispatch()["outcome"], "INCOMPATIBLE")
        self.assertFalse(Identity.objects.exists())
        self.assertFalse(Delivery.objects.exists())

    def test_prepare_rollback_and_commit_ack_loss_never_send(self):
        self.post()
        with self.assertRaises(RuntimeError), transaction.atomic():
            # Exercise server function on this transaction, not the client connection.
            with connection.cursor() as cursor:
                cursor.execute("SELECT public.report_dispatch_prepare(%s,%s,%s,%s,%s,%s,%s)",
                    [Attempt.objects.get().pk, Attempt.objects.get().execution_id,
                     operations.barrier_status()["generation"], RELEASE, ROOT, HOST.host_id, HOST.boot_id])
            raise RuntimeError("rollback")
        self.assertFalse(Delivery.objects.exists())
        self.assertFalse(Identity.objects.exists())
        db = self.database()
        real_prepare = db.prepare
        def lost(*args, **kwargs):
            real_prepare(*args, **kwargs)
            raise DispatchError("dispatch_database_state_unknown")
        send = Mock()
        with patch.object(db, "prepare", side_effect=lost), self.assertRaises(DispatchError):
            self.dispatch(send, db)
        self.assertTrue(Delivery.objects.exists())
        self.assertEqual(self.dispatch(send)["outcome"], "DELIVERY_UNCERTAIN")
        send.assert_not_called()

    def test_delivery_is_not_execution_authority_and_receipt_fences_startup(self):
        self.post()
        delivery = self.prepare()
        identity = Identity.objects.get()
        observed = runtime.RuntimeIdentity(HOST, identity.unit_name, uuid4(),
            "/system.slice/"+identity.unit_name, 12345, 1234, 123456)
        context = supervision.LaunchContext(identity.pk, observed)
        with self.assertRaisesMessage(legacy.FinalizationError, "launch_binding_invalid"):
            executor.claim(identity.attempt_id, supervision=context)
        from signaling.test_report_launcher_postgresql import CONSUME, ENVELOPE
        with connection.cursor() as cursor:
            cursor.execute(ENVELOPE, [delivery["launch_id"]])
            envelope = cursor.fetchone()[0]
            if not isinstance(envelope, str):
                envelope = json.dumps(envelope)
            cursor.execute(CONSUME, [delivery["launch_id"], delivery["request_id"], delivery["generation"],
                2001, HOST.host_id, HOST.boot_id, "3"*64, envelope])
        current = executor.claim(identity.attempt_id, supervision=context)
        self.assertEqual(current.state, "PROCESSING")
        self.assertEqual(current.execution_id, identity.execution_id)
        with self.assertRaises(legacy.FinalizationError):
            with transaction.atomic():
                admission.assert_execution(current.pk, identity.expected_execution_id)
        self.assertEqual(self.dispatch()["outcome"], "DELIVERY_UNCERTAIN")

    def test_flags_fail_closed_and_legacy_cannot_bypass_async(self):
        with override_settings(REPORT_EXECUTOR_ENABLED=False):
            self.assertEqual(self.post().status_code, 503)
        with override_settings(REPORT_ADMISSION_ENABLED=False):
            with self.assertRaisesMessage(legacy.FinalizationError, "synchronous_finalization_disabled"):
                legacy._require_legacy_mutation()
        with self.assertRaisesMessage(CommandError, "dispatch_disabled"):
            call_command("dispatch_report_publication")

    def test_http_dispatch_launcher_claim_and_atomic_completion_contract(self):
        from report_launcher.service import Launcher
        from report_launcher.database import Database as LauncherDatabase
        response = self.post()
        before = Attempt.objects.get()
        frozen_hash, frozen_number = before.version.snapshot_sha256, before.version.report.official_number
        root_catalog, manager = Mock(), Mock()
        root_catalog.dispatcher_uid = 2001
        root_catalog.validate.return_value = {"root": ROOT, "release_id": RELEASE,
            "bundle_sha256": "1"*64, "manifest_sha256": "2"*64,
            "python": ROOT+"/.venv/bin/python", "environment_file": "/etc/synthetic.env",
            "private_report_root": "/var/lib/analise/reports"}
        manager.start.return_value = 41  # No systemd, conversion, or real publication.
        connection.ensure_connection()
        launcher = Launcher(LauncherDatabase(connection.connection.info.dsn), root_catalog, manager,
            host_reader=lambda: (HOST.host_id, HOST.boot_id), audit_writer=Mock())
        def transport(delivery):
            return launcher.handle({"protocol": 1, "operation": "start", "request_id": str(delivery["request_id"]),
                "launch_id": str(delivery["launch_id"]), "expected_barrier_generation": str(delivery["generation"])},
                {"uid": 2001})["code"]
        self.assertEqual(self.dispatch(transport)["outcome"], "JOB_OBSERVED")
        self.assertEqual(Receipt.objects.count(), 1)
        manager.start.assert_called_once()
        self.dispatch(transport)
        manager.start.assert_called_once()
        identity = Identity.objects.get()
        observed = runtime.RuntimeIdentity(HOST, identity.unit_name, uuid4(),
            "/system.slice/"+identity.unit_name, 12345, 1234, 123456)
        attempt = executor.claim(identity.attempt_id, supervision=supervision.LaunchContext(identity.pk, observed))
        attempt.state = "STORING"
        attempt.save(update_fields=["state"])
        artifacts = [ReportArtifact.objects.create(version=attempt.version, kind=kind,
            storage_key=f"{attempt.version_id}/{attempt.execution_id}/{uuid4()}.{kind.lower()}",
            download_name="synthetic", content_type=mime, size=1, sha256="a"*64)
            for kind, mime in (("DOCX", "application/octet-stream"), ("PDF", "application/pdf"))]
        with patch.object(Slot, "save", side_effect=DatabaseError("synthetic commit failure")):
            with self.assertRaises(DatabaseError):
                executor._complete(attempt, artifacts)
        self.assertEqual(Attempt.objects.get().state, "STORING")
        self.assertEqual(Slot.objects.get().attempt_id, attempt.pk)
        self.assertIsNone(attempt.version.__class__.objects.get(pk=attempt.version_id).finalized_at)
        executor._complete(attempt, artifacts)
        self.assertIsNone(Slot.objects.get().attempt_id)
        self.assertEqual(Attempt.objects.get().version.snapshot_sha256, frozen_hash)
        self.assertEqual(Attempt.objects.get().version.report.official_number, frozen_number)
        status = self.client.get(response["Location"])
        self.assertTrue(status.json()["success"])
        self.assertEqual(status.json()["publication_phase"], "FINALIZED")
        self.move("DRAINING")
        with self.assertRaisesMessage(Exception, "deployment_not_quiescent"):
            self.move("DEPLOYING")  # Completion is not proof of physical termination.

    def test_empty_candidate_and_database_failure_are_safe(self):
        send = Mock()
        self.assertEqual(self.dispatch(send)["outcome"], "NO_ADMISSION")
        send.assert_not_called()
        db = self.database()
        with patch.object(db, "connect", side_effect=OSError("secret connection info")):
            with self.assertRaisesMessage(DispatchError, "dispatch_database_state_unknown"):
                self.dispatch(send, db)
        send.assert_not_called()

    def test_prepared_delivery_is_diagnosed_without_writes_and_http_db_failure_is_unknown(self):
        with patch.object(admission, "admit", side_effect=DatabaseError("private DSN")):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"success": False, "code": "publication_state_unknown"})
        self.post()
        self.prepare()
        from signaling.report_dispatcher import evaluate
        before = (Event.objects.count(), Delivery.objects.count(), Launch.objects.get().requested_at)
        result = evaluate()
        self.assertEqual(result["outcome"], "UNCERTAIN")
        self.assertIn("dispatch_delivery_not_reissued", result["reasons"])
        self.assertEqual(before, (Event.objects.count(), Delivery.objects.count(), Launch.objects.get().requested_at))

    def test_restricted_roles_can_prepare_but_never_read_intentions_or_consume(self):
        self.post()
        suffix = uuid4().hex[:10]
        owner, dispatcher, http = [prefix+suffix for prefix in ("dispatch_owner_", "dispatch_runtime_", "dispatch_http_")]
        with connection.cursor() as c:
            c.execute("SELECT current_user")
            original = c.fetchone()[0]
            c.execute(f'CREATE ROLE "{owner}" NOLOGIN')
            c.execute(f'CREATE ROLE "{dispatcher}" LOGIN')
            c.execute(f'CREATE ROLE "{http}" NOLOGIN')
            for role in (owner, dispatcher, http):
                c.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            for table in ("reportpublicationslot", "reportfinalizationattempt", "reportdeploymentbarrier",
                    "reportexecutionidentity", "reportlaunch", "reportdispatchdelivery", "reportreleaseauthorization",
                    "technicalreportversion", "technicalreport", "reportartifact"):
                c.execute(f'GRANT SELECT ON public.signaling_{table} TO "{owner}"')
            for table in ("reportpublicationslot", "reportfinalizationattempt"):
                c.execute(f'GRANT UPDATE ON public.signaling_{table} TO "{owner}"')
            for table in ("reportexecutionidentity", "reportlaunch", "reportdispatchdelivery", "reportoperationalevent"):
                c.execute(f'GRANT INSERT ON public.signaling_{table} TO "{owner}"')
            for function in FUNCTIONS:
                c.execute(f'ALTER FUNCTION public.{function} OWNER TO "{owner}"')
                c.execute(f'GRANT EXECUTE ON FUNCTION public.{function} TO "{dispatcher}"')
        try:
            import psycopg
            from psycopg.conninfo import make_conninfo
            db = DispatchDatabase(make_conninfo(connection.connection.info.dsn, user=dispatcher))
            db.verify_privileges()
            with self.assertRaisesMessage(DispatchError, "dispatch_database_privileges_unsafe"):
                self.database().verify_privileges()
            self.assertTrue(self.prepare(db)["fresh"])
            for role in (dispatcher, http):
                with transaction.atomic(), connection.cursor() as c:
                    c.execute(f'SET LOCAL ROLE "{role}"')
                    for sql in ("SELECT * FROM public.signaling_technicalreportversion",
                            "SELECT * FROM public.signaling_reportdispatchdelivery",
                            "DELETE FROM public.signaling_reportdispatchdelivery",
                            "UPDATE public.signaling_reportpublicationslot SET attempt_id=NULL,execution_id=NULL",
                            "SELECT public.report_launcher_status(NULL::uuid)",
                            "SELECT public.report_launcher_consume(NULL::uuid,NULL::uuid,NULL::uuid,2001,'x',NULL::uuid,'x','{}'::jsonb)"):
                        with self.assertRaises(DatabaseError), transaction.atomic():
                            c.execute(sql)
                    if role == http:
                        with self.assertRaises(DatabaseError), transaction.atomic():
                            c.execute("SELECT public.report_dispatch_candidate()")
        finally:
            with connection.cursor() as c:
                for function in FUNCTIONS:
                    c.execute(f'ALTER FUNCTION public.{function} OWNER TO "{original}"')
                for role in (dispatcher, http, owner):
                    c.execute(f'DROP OWNED BY "{role}"')
                    c.execute(f'DROP ROLE "{role}"')


# Helpers only: run the legacy suite explicitly, not accidentally via this alias.
del HttpFixture
