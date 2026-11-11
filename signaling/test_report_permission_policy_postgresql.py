"""Exercise the declarative grants ONLY with temporary test-database roles.

Never invokes the provisioning generator/script or touches host users/services.
"""
from contextlib import contextmanager
from unittest import skipUnless
from uuid import uuid4
from unittest.mock import patch

from django.db import connection, transaction, DatabaseError
from django.contrib.auth import get_user_model
from django.test import override_settings
from scripts.report_permission_policy import grant_statements, ownership_statements, LAUNCH_FUNCTIONS, DISPATCH_FUNCTIONS
from signaling.test_report_async_postgresql import AsyncPublicationPostgreSQLTests as Helpers
from signaling.test_report_operations_postgresql import OperationsFixture
from signaling.models import (ReportReleaseAuthorization as Release, ReportExecutionIdentity as Identity,
    ReportFinalizationAttempt as Attempt, ReportPublicationSlot as Slot)
from signaling import report_operations as operations, report_executor as executor, report_supervision as supervision
from signaling import report_systemd_runtime as runtime, report_deletion
from signaling.test_report_supervision import HOST, RELEASE
from signaling.test_pdf_conversion import fake_pdf


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL")
class RuntimePermissionPolicyTests(OperationsFixture):
    headers = Helpers.headers
    client_for_thread = Helpers.client_for_thread
    post = Helpers.post
    retry_http = Helpers.retry_http
    database = Helpers.database
    prepare = Helpers.prepare

    def setUp(self):
        super().setUp()
        config = override_settings(REPORT_FINALIZATION_ENABLED=True, REPORT_ASYNC_PUBLICATION_ENABLED=True)
        config.enable()
        self.addCleanup(config.disable)
        self.key = uuid4()
        from signaling.surveys import ANALYSIS_SESSION_KEY
        session = self.client.session
        session[ANALYSIS_SESSION_KEY] = {"view_mode": "individual", "map_data": []}
        session.save()
        Release.objects.create(release_id=RELEASE, bundle_sha256="1"*64, manifest_sha256="2"*64,
            execution_contract=operations.execution_contract(), approved_by=uuid4())
        suffix = uuid4().hex[:10]
        self.roles = {name: "policy_"+name+"_"+suffix for name in ("http", "executor", "dispatcher", "launcher", "owner")}
        with connection.cursor() as c:
            c.execute("SELECT current_user")
            self.original_owner = c.fetchone()[0]
            for name, role in self.roles.items():
                c.execute(f'CREATE ROLE "{role}" {"NOLOGIN" if name == "owner" else "LOGIN"} NOINHERIT')
            for sql in grant_statements(self.roles) + ownership_statements(self.roles["owner"]):
                c.execute(sql)
        self.addCleanup(self.remove_roles)

    def remove_roles(self):
        with connection.cursor() as c:
            c.execute("RESET ROLE")
            for sql in ownership_statements(self.original_owner):
                c.execute(sql)
            for role in (*[self.roles[name] for name in ("http", "executor", "dispatcher", "launcher")], self.roles["owner"]):
                c.execute(f'DROP OWNED BY "{role}"')
                c.execute(f'DROP ROLE "{role}"')

    @contextmanager
    def as_role(self, name):
        with connection.cursor() as c:
            c.execute(f'SET ROLE "{self.roles[name]}"')
        try:
            yield
        finally:
            with connection.cursor() as c:
                c.execute("RESET ROLE")

    def test_http_can_admit_replay_and_reject_operational_mutations(self):
        with self.as_role("http"):
            self.assertEqual(self.post().status_code, 202)
            self.assertEqual(self.post().status_code, 202)
            self.assertEqual(self.retry_http(Attempt.objects.get()).status_code, 202)
            for sql in ("UPDATE public.signaling_technicalreportversion SET snapshot='{}'",
                    "UPDATE public.signaling_reportfinalizationattempt SET state='FINALIZED'",
                    "DELETE FROM public.signaling_reportlauncherreceipt",
                    "SELECT * FROM public.signaling_reportreleaseauthorization",
                    "SELECT public.report_dispatch_candidate()"):
                with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as c:
                    c.execute(sql)

    def test_dispatcher_and_launcher_actual_login_guards_and_executor_claim(self):
        self.post()
        import psycopg
        from psycopg.conninfo import make_conninfo
        from signaling.report_active_dispatcher import DispatchDatabase
        from report_launcher.database import Database as LauncherDatabase
        from signaling.test_report_async_postgresql import ROOT
        from signaling.test_report_launcher_postgresql import ENVELOPE, CONSUME
        connection.ensure_connection()
        base = connection.connection.info.dsn
        dispatcher = DispatchDatabase(make_conninfo(base, user=self.roles["dispatcher"]))
        dispatcher.verify_privileges()
        delivery = self.prepare(dispatcher)
        launcher = LauncherDatabase(make_conninfo(base, user=self.roles["launcher"]))
        launcher.verify_privileges()
        envelope = launcher.envelope(delivery["launch_id"])
        request = {"launch_id": delivery["launch_id"], "request_id": delivery["request_id"],
            "expected_barrier_generation": delivery["generation"]}
        self.assertTrue(launcher.consume(request, {"uid": 2001}, HOST.host_id, HOST.boot_id, "3"*64, envelope)["fresh"])
        launcher.record_job(delivery["launch_id"], delivery["request_id"], 41)
        identity = Identity.objects.get()
        observed = runtime.RuntimeIdentity(HOST, identity.unit_name, uuid4(), "/system.slice/"+identity.unit_name, 12345, 1234, 123456)
        with self.as_role("executor"):
            claimed = executor.claim(identity.attempt_id, supervision=supervision.LaunchContext(identity.pk, observed))
            self.assertEqual(claimed.state, "PROCESSING")
            self.assertEqual(claimed.execution_id, identity.execution_id)
            from signaling import report_finalization as finalization, report_admission as admission
            from signaling.report_storage import PrivateReportStorage
            claimed.state = "STORING"
            claimed.save(update_fields=["state"])
            storage = PrivateReportStorage()
            artifacts = [finalization._store(claimed, storage, kind, data,
                assert_run=admission.assert_execution) for kind, data in
                (("DOCX", b"synthetic-docx"), ("PDF", fake_pdf()))]
            executor._complete(claimed, artifacts)
            self.assertIsNone(Slot.objects.get().attempt_id)
            with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE public.signaling_technicalreportversion SET snapshot='{}'")
            with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as c:
                c.execute("SELECT public.report_dispatch_candidate()")

    def test_http_audited_physical_deletion_still_works_with_column_grants(self):
        self.post()
        # Synthetic finalized metadata, no rendering, conversion or real report.
        attempt = Attempt.objects.get()
        identity = supervision.prepare(attempt_id=attempt.pk, expected_execution_id=attempt.execution_id)
        from django.utils import timezone
        now = timezone.now()
        attempt.state = "FINALIZED"
        attempt.save(update_fields=["state"])
        attempt.version.finalized_at = now
        attempt.version.save(update_fields=["finalized_at"])
        attempt.version.report.number_assigned_at = now
        attempt.version.report.save(update_fields=["number_assigned_at"])
        Slot.objects.update(attempt=None, execution_id=None)
        from django.contrib.auth.models import Permission
        user = get_user_model().objects.get(pk=self.client.session["_auth_user_id"])
        user.user_permissions.add(Permission.objects.get(codename="delete_official_reports"))
        with self.as_role("http"):
            audit = report_deletion.delete_report(user=user, report_id=attempt.version.report_id,
                operation_id=uuid4(), confirm_number=attempt.version.report.official_number)
            self.assertEqual(audit.cleanup_state, "COMPLETE")
        self.assertFalse(Attempt.objects.exists())
        identity.refresh_from_db()
        self.assertIsNone(identity.attempt_id)


del Helpers
