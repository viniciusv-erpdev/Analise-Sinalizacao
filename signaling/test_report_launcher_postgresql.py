"""External SQL contract on real PostgreSQL. No real manager or publication."""
import json
from unittest import skipUnless
from uuid import UUID, uuid4

from django.db import connection, transaction, DatabaseError

from report_launcher.validation import validate_envelope
from signaling import report_operations as operations
from signaling.models import ReportLaunch as Launch, ReportLauncherReceipt as Receipt, ReportOperationalEvent as Event
from signaling.test_report_operations_postgresql import OperationsFixture
from signaling.test_report_supervision import HOST, RELEASE
from signaling import report_supervision as supervision
from signaling.models import ReportReleaseAuthorization as Release

ENVELOPE = "SELECT public.report_launcher_envelope(%s::uuid)"
CONSUME = "SELECT public.report_launcher_consume(%s::uuid,%s::uuid,%s::uuid,%s,%s,%s::uuid,%s,%s::jsonb)"
FUNCTIONS = ("report_launcher_envelope(uuid)", "report_launcher_status(uuid)",
    "report_launcher_consume(uuid,uuid,uuid,integer,text,uuid,text,jsonb)", "report_launcher_job(uuid,uuid,bigint)")


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL")
class ReportLauncherPostgreSQLTests(OperationsFixture):
    def setUp(self):
        super().setUp()
        self.attempt = self.admit()
        self.plan = supervision.prepare(attempt_id=self.attempt.pk, expected_execution_id=self.attempt.execution_id)
        Release.objects.create(release_id=RELEASE, bundle_sha256="1"*64, manifest_sha256="2"*64,
            execution_contract=operations.execution_contract(), approved_by=uuid4())
        self.launch = operations.request_launch(identity_id=self.plan.pk)
        self.request = uuid4()
        self.generation = operations.barrier_status()["generation"]

    def envelope(self):
        with connection.cursor() as cursor:
            cursor.execute(ENVELOPE, [self.launch.pk])
            value = cursor.fetchone()[0]
        return json.loads(value) if isinstance(value, str) else value

    def consume(self, envelope=None, request=None, generation=None):
        with connection.cursor() as cursor:
            cursor.execute(CONSUME, [self.launch.pk, request or self.request, generation or self.generation,
                2001, HOST.host_id, HOST.boot_id, "3"*64, json.dumps(envelope if envelope is not None else self.envelope())])
            value = cursor.fetchone()[0]
        return json.loads(value) if isinstance(value, str) else value

    def test_json_only_validator_matches_real_persisted_intent(self):
        envelope = self.envelope()
        self.assertEqual(validate_envelope(envelope, {"root": self.plan.release_root, "release_id": RELEASE,
            "bundle_sha256": "1"*64, "manifest_sha256": "2"*64}, HOST.host_id, HOST.boot_id)[1], str(self.plan.pk))

    def test_consumption_receipt_epoch_and_audit_confirm_together(self):
        result = self.consume()
        self.assertTrue(result["fresh"])
        self.launch.refresh_from_db()
        self.assertEqual(self.launch.state, "UNCERTAIN")
        receipt = Receipt.objects.get()
        self.assertEqual(receipt.dispatch_id, self.launch.dispatch_id)
        self.assertEqual(receipt.barrier_generation, self.generation)
        self.assertEqual(self.attempt.execution_id, self.plan.expected_execution_id)
        self.assertEqual(Event.objects.get(kind="LAUNCHER_CONSUMED").actor, self.request)
        # Lost reply/restart cannot obtain a second ticket, even with a new request.
        self.assertFalse(self.consume()["fresh"])
        self.assertFalse(self.consume(request=uuid4())["fresh"])
        self.assertEqual(Receipt.objects.count(), 1)

    def test_two_connections_only_one_receives_fresh_authorization(self):
        envelope = self.envelope()
        def run():
            try:
                return self.consume(envelope=envelope, request=uuid4())
            except DatabaseError:
                return "busy"
        results = self.race(run, run)
        self.assertEqual(sum(isinstance(row, dict) and row["fresh"] for row in results), 1)
        self.assertEqual(Receipt.objects.count(), 1)

    def test_changed_barrier_or_generation_refuses_consumption(self):
        envelope = self.envelope()
        self.move("DRAINING")
        self.move("OPEN")
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.consume(envelope)
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.consume(generation=uuid4())
        self.assertFalse(Receipt.objects.exists())
        self.assertEqual(Launch.objects.get().state, "REQUESTED")

    def test_changed_intent_fails_atomic_compare(self):
        envelope = self.envelope()
        Launch.objects.filter(pk=self.launch.pk).update(contract_sha256="4"*64)
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.consume(envelope)
        self.assertFalse(Receipt.objects.exists())

    def test_legacy_uncertain_launch_is_not_taken_over(self):
        operations.begin_dispatch(launch_id=self.launch.pk, actor=self.actor, event_id=uuid4())
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.consume()
        self.assertFalse(Receipt.objects.exists())

    def test_rollback_does_not_burn_receipt_or_leave_partial_state(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.consume()
            raise RuntimeError("synthetic rollback")
        self.assertFalse(Receipt.objects.exists())
        self.assertEqual(Launch.objects.get().state, "REQUESTED")
        self.assertFalse(Event.objects.exists())

    def test_job_observation_is_idempotent_not_confirmation_or_release(self):
        self.consume()
        with connection.cursor() as cursor:
            for _ in range(2):
                cursor.execute("SELECT public.report_launcher_job(%s,%s,41::bigint)", [self.launch.pk, self.request])
        self.assertEqual(Launch.objects.get().job_id, 41)
        self.assertEqual(Launch.objects.get().state, "UNCERTAIN")
        self.assertEqual(Event.objects.filter(kind="LAUNCHER_JOB_OBSERVED").count(), 1)
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT public.report_launcher_job(%s,%s,42::bigint)", [self.launch.pk, self.request])

    def test_barrier_still_refuses_deploy_after_consumption(self):
        self.consume()
        self.move("DRAINING")
        with self.assertRaisesMessage(Exception, "deployment_not_quiescent"):
            self.move("DEPLOYING")

    def test_runtime_sql_roles_have_only_explicit_entry_points(self):
        # Roles are created ONLY inside this isolated test cluster, never by migration.
        suffix = uuid4().hex[:12]
        owner, runtime, dispatcher, http = [prefix+suffix for prefix in ("rl_owner_", "rl_runtime_", "rl_dispatch_", "rl_http_")]
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            original = cursor.fetchone()[0]
            for role in (owner, runtime, dispatcher, http):
                login = "LOGIN" if role == runtime else "NOLOGIN"
                cursor.execute(f'CREATE ROLE "{role}" {login}')
            cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{owner}","{runtime}","{dispatcher}","{http}"')
            tables = ("reportlaunch", "reportlauncherreceipt", "reportoperationalevent", "reportpublicationslot",
                "reportfinalizationattempt", "reportexecutionidentity", "technicalreportversion", "technicalreport",
                "reportreleaseauthorization", "reportdeploymentbarrier", "reportartifact")
            for table in tables:
                cursor.execute(f'GRANT SELECT ON public.signaling_{table} TO "{owner}"')
            for table in ("reportpublicationslot", "reportfinalizationattempt", "reportexecutionidentity", "reportlaunch"):
                cursor.execute(f'GRANT UPDATE ON public.signaling_{table} TO "{owner}"')
            for table in ("reportlauncherreceipt", "reportoperationalevent"):
                cursor.execute(f'GRANT INSERT ON public.signaling_{table} TO "{owner}"')
            for function in FUNCTIONS:
                cursor.execute(f'ALTER FUNCTION public.{function} OWNER TO "{owner}"')
                cursor.execute(f'GRANT EXECUTE ON FUNCTION public.{function} TO "{runtime}"')
            cursor.execute(f'GRANT SELECT ON public.report_dispatch_projection TO "{dispatcher}"')
        try:
            for role in (runtime, dispatcher, http):
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute(f'SET LOCAL ROLE "{role}"')
                    if role == runtime:
                        from report_launcher.database import Database
                        import psycopg
                        from psycopg.conninfo import conninfo_to_dict
                        dsn = connection.connection.info.dsn
                        def connect_role(*args, **kwargs):
                            config = conninfo_to_dict(dsn)
                            config.update(kwargs)
                            config["user"] = runtime
                            return psycopg.connect(**config)
                        Database("not-used", connect=connect_role).verify_privileges()
                        from report_launcher.protocol import Rejected
                        with self.assertRaisesMessage(Rejected, "database_privileges_unsafe"):
                            Database(dsn).verify_privileges()
                        self.assertTrue(self.consume()["fresh"])
                    else:
                        with self.assertRaises(DatabaseError), transaction.atomic():
                            cursor.execute(ENVELOPE, [self.launch.pk])
                        with self.assertRaises(DatabaseError), transaction.atomic():
                            cursor.execute("SELECT public.report_launcher_status(%s)", [self.launch.pk])
                        with self.assertRaises(DatabaseError), transaction.atomic():
                            self.consume()
                    for sql in ("SELECT * FROM public.signaling_reportlauncherreceipt",
                                "UPDATE public.signaling_reportlaunch SET state='REQUESTED'",
                                "DELETE FROM public.signaling_reportlauncherreceipt"):
                        with self.assertRaises(DatabaseError), transaction.atomic():
                            cursor.execute(sql)
                    if role == dispatcher:
                        cursor.execute("SELECT * FROM public.report_dispatch_projection")
                        self.assertEqual(len(cursor.fetchall()), 1)
        finally:
            with connection.cursor() as cursor:
                for function in FUNCTIONS:
                    cursor.execute(f'ALTER FUNCTION public.{function} OWNER TO "{original}"')
                for role in (runtime, dispatcher, http, owner):
                    cursor.execute(f'DROP OWNED BY "{role}"')
                    cursor.execute(f'DROP ROLE "{role}"')
