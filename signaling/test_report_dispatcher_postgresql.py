"""Real PostgreSQL diagnostic snapshots. Never starts a unit or generates reports."""
from contextlib import ExitStack
from io import StringIO
import json
from threading import Event
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command, CommandError
from django.db import connection, transaction, OperationalError
from django.test import override_settings

from signaling import report_dispatcher as dispatcher, report_operations as operations
from signaling import report_admission as admission, report_executor as executor
from signaling import report_supervision as supervision, report_systemd_runtime as runtime
from signaling.report_storage import PrivateReportStorage
from signaling.models import (ReportPublicationSlot as Slot, ReportFinalizationAttempt as Attempt,
    ReportExecutionIdentity as Identity, ReportLaunch as Launch, ReportReleaseAuthorization as Release,
    ReportDeploymentBarrier as Barrier, ReportOperationalEvent, ReportArtifact,
    TechnicalReportVersion, TechnicalReport, ReportAnnualCounter)
from signaling.report_snapshots import canonical
from signaling.report_snapshots import prepare_photos
from signaling.test_report_finalization import photo_upload
from django.http import QueryDict
from signaling.test_report_operations_postgresql import OperationsFixture
from signaling.test_report_supervision import RELEASE, observations


@skipUnless(connection.vendor == "postgresql", "Requires isolated real PostgreSQL")
class ReportDispatcherPostgreSQLTests(OperationsFixture):
    def prepared(self):
        self.attempt = self.admit()
        self.plan = supervision.prepare(attempt_id=self.attempt.pk, expected_execution_id=self.attempt.execution_id)
        self.approve()
        return self.attempt

    def approve(self, **changes):
        return Release.objects.create(**({"release_id": RELEASE, "bundle_sha256": "1"*64,
            "manifest_sha256": "2"*64, "execution_contract": operations.execution_contract(),
            "approved_by": uuid4()} | changes))

    def stored(self):
        return canonical({model.__name__: list(model.objects.order_by("pk").values()) for model in
            (Slot, Attempt, Identity, Launch, Release, Barrier, ReportOperationalEvent,
             ReportArtifact, TechnicalReportVersion, TechnicalReport, ReportAnnualCounter)})

    def diagnose(self):
        with ExitStack() as stack:
            for module, names in ((admission, ("coordination", "assert_execution", "load_inputs")),
                    (operations, ("begin_dispatch", "request_launch", "observe_launch", "transition_barrier")),
                    (supervision, ("prepare", "context")), (executor, ("claim", "execute")),
                    (runtime, ("host_identity", "manager_properties")), (PrivateReportStorage, ("__init__",))):
                for name in names:
                    stack.enter_context(patch.object(module, name,
                        side_effect=AssertionError("Diagnostic must not mutate or inspect external state")))
            return dispatcher.evaluate()

    def test_empty_diagnostic_creates_no_singletons(self):
        before = self.stored()
        result = self.diagnose()
        self.assertEqual(result["outcome"], "NO_ADMISSION")
        self.assertEqual(result["barrier"]["generation"], "00000000-0000-0000-0000-000000000000")
        self.assertIsNone(result["candidate"])
        self.assertEqual(self.stored(), before)

    def test_eligible_is_read_only_and_never_authorizes(self):
        self.prepared()
        before, statements = self.stored(), []

        def capture(execute, sql, params, many, context):
            statements.append(sql.upper())
            return execute(sql, params, many, context)

        with connection.execute_wrapper(capture):
            result = self.diagnose()
        self.assertEqual(result["outcome"], "ELIGIBLE")
        self.assertTrue(result["eligible"])
        self.assertFalse(result["authorization_granted"])
        self.assertTrue(result["potentially_stale"])
        self.assertFalse(result["database_changed_during_observation"])
        self.assertEqual(self.stored(), before)
        self.assertEqual(sum("REPEATABLE READ, READ ONLY" in sql for sql in statements), 2)
        self.assertFalse(any("FOR UPDATE" in sql or "ADVISORY" in sql for sql in statements))
        self.assertFalse(any(sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements))
        self.assertTrue(all(value == "not_verified" for value in result["external_checks"].values()))

    def test_no_identity_is_preparation_required_not_prepared_implicitly(self):
        self.admit()
        self.approve()
        self.assertEqual(self.diagnose()["outcome"], "PREPARATION_REQUIRED")
        self.assertFalse(Identity.objects.exists())

    def test_missing_catalog_and_legacy_contract_are_incompatible(self):
        attempt = self.admit()
        self.assertEqual(self.diagnose()["outcome"], "INCOMPATIBLE")
        self.approve()
        Attempt.objects.filter(pk=attempt.pk).update(execution_contract={})
        self.assertEqual(self.diagnose()["outcome"], "INCOMPATIBLE")

    def test_release_contract_and_bundle_metadata_are_validated(self):
        self.admit()
        self.approve(execution_contract={"launcher": 999}, bundle_sha256="bad")
        self.assertEqual(self.diagnose()["outcome"], "INCOMPATIBLE")

    def test_invalid_approved_bundle_digest_is_not_eligible(self):
        self.admit()
        self.approve(bundle_sha256="bad")
        self.assertEqual(self.diagnose()["outcome"], "INCOMPATIBLE")

    def test_supervision_release_and_user_configuration_mismatch(self):
        self.prepared()
        for settings in ({"REPORT_EXECUTOR_RELEASE_ID": "c"*40}, {"REPORT_EXECUTOR_SYSTEMD_USER": "other"}):
            with override_settings(**settings):
                self.assertEqual(self.diagnose()["outcome"], "INCOMPATIBLE")

    def test_flags_disabled_do_not_hide_diagnostic_eligibility(self):
        self.prepared()
        with override_settings(REPORT_ADMISSION_ENABLED=False, REPORT_EXECUTOR_ENABLED=False,
                               REPORT_SYSTEMD_SUPERVISION_ENABLED=False):
            result = self.diagnose()
        self.assertEqual(result["outcome"], "ELIGIBLE")
        self.assertFalse(any(result["activation_flags"].values()))
        self.assertFalse(result["authorization_granted"])

    def test_draining_and_deploying_block_without_writes(self):
        self.move("DRAINING")
        result = self.diagnose()
        self.assertEqual(result["outcome"], "MAINTENANCE")
        self.assertEqual(result["barrier"]["generation"], str(Barrier.objects.get().generation))
        self.move("DEPLOYING")
        before = self.stored()
        self.assertEqual(self.diagnose()["outcome"], "MAINTENANCE")
        self.assertEqual(before, self.stored())

    def test_admitted_maintenance_preserves_identity_and_inputs(self):
        self.prepared()
        self.move("DRAINING")
        before = self.stored()
        self.assertEqual(self.diagnose()["outcome"], "MAINTENANCE")
        self.assertEqual(before, self.stored())

    def test_requested_launch_is_distinct_from_eligible(self):
        self.prepared()
        launch = operations.request_launch(identity_id=self.plan.pk)
        result = self.diagnose()
        self.assertEqual(result["outcome"], "LAUNCH_REQUESTED")
        self.assertEqual(result["candidate"]["launch_id"], str(launch.pk))
        self.assertFalse(result["eligible"])
        self.assertIsNone(Launch.objects.get().dispatch_id)

    def test_uncertain_confirmed_and_terminal_launches_remain_observations(self):
        self.prepared()
        launch = operations.request_launch(identity_id=self.plan.pk)
        ticket = operations.begin_dispatch(launch_id=launch.pk, actor=self.actor, event_id=uuid4())
        self.assertEqual(self.diagnose()["outcome"], "UNCERTAIN")
        invocation = uuid4()
        operations.observe_launch(launch_id=launch.pk, dispatch_id=ticket, actor=self.actor,
            event_id=uuid4(), invocation_id=invocation, job_id=41)
        self.assertEqual(self.diagnose()["outcome"], "LAUNCH_REQUESTED")
        operations.observe_launch(launch_id=launch.pk, dispatch_id=ticket, actor=self.actor,
            event_id=uuid4(), invocation_id=invocation, terminal_result="signal")
        before = self.stored()
        result = self.diagnose()
        self.assertEqual(result["outcome"], "UNCERTAIN")
        self.assertIn("termination_unverified", result["reasons"])
        self.assertEqual(before, self.stored())
        self.assertEqual(Slot.objects.get().attempt_id, self.attempt.pk)

    def test_execution_in_progress_is_not_redispatched(self):
        self.prepared()
        context = supervision.LaunchContext(self.plan.pk, runtime.validate_runtime(self.plan, **observations(self.plan)))
        executor.claim(self.attempt.pk, supervision=context)
        self.assertEqual(self.diagnose()["outcome"], "EXECUTION_IN_PROGRESS")

    def test_failed_and_interrupted_attempts_are_uncertain(self):
        attempt = self.admit()
        for state in ("FAILED", "INTERRUPTED"):
            Attempt.objects.filter(pk=attempt.pk).update(state=state)
            self.assertEqual(self.diagnose()["outcome"], "UNCERTAIN")

    def test_slot_epoch_mismatch_is_inconsistent(self):
        self.prepared()
        Slot.objects.update(execution_id=uuid4())
        self.assertIn("slot_execution_mismatch", self.diagnose()["reasons"])
        self.assertEqual(self.diagnose()["outcome"], "INCONSISTENT")

    def test_identity_epoch_metadata_is_validated_without_repair(self):
        self.prepared()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE signaling_reportexecutionidentity SET expected_execution_id = %s WHERE id = %s",
                           [uuid4(), self.plan.pk])
        before = self.stored()
        self.assertIn("identity_metadata_invalid", self.diagnose()["reasons"])
        self.assertEqual(before, self.stored())

    def test_launch_contract_hash_divergence_is_inconsistent(self):
        self.prepared()
        operations.request_launch(identity_id=self.plan.pk)
        Launch.objects.update(contract_sha256="f"*64)
        self.assertIn("launch_metadata_invalid", self.diagnose()["reasons"])

    def test_original_photo_metadata_is_verified_without_opening_files(self):
        attempt = admission.admit(point_id=self.point.pk, identity=self.identity,
            credentials=self.grant.credentials, user_id=self.client.session["_auth_user_id"],
            key=uuid4(), expected_revision=1, parameters=QueryDict(),
            analysis_state={"view_mode": "individual", "map_data": []}, photos=prepare_photos([photo_upload()]))
        self.approve()
        self.assertEqual(self.diagnose()["outcome"], "PREPARATION_REQUIRED")
        ReportArtifact.objects.filter(version=attempt.version).update(sha256="f"*64)
        self.assertIn("photo_metadata_invalid", self.diagnose()["reasons"])

    def test_unowned_attempt_is_not_used_as_a_queue(self):
        self.admit()
        Slot.objects.update(attempt=None, execution_id=None)
        result = self.diagnose()
        self.assertEqual(result["outcome"], "INCONSISTENT")
        self.assertIsNone(result["candidate"])

    def test_finalized_history_with_empty_slot_is_still_unverified(self):
        self.prepared()
        Attempt.objects.update(state="FINALIZED")  # Synthetic metadata; no publication.
        Slot.objects.update(attempt=None, execution_id=None)
        self.assertEqual(self.diagnose()["outcome"], "UNCERTAIN")

    def test_snapshot_corruption_is_reported_without_private_content(self):
        self.prepared()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE signaling_technicalreportversion SET snapshot = %s WHERE id = %s",
                [json.dumps({"private": "PRIVATE_SENTINEL"}), self.attempt.version_id])
        result = self.diagnose()
        self.assertEqual(result["outcome"], "INCONSISTENT")
        self.assertIn("snapshot_integrity_failed", result["reasons"])
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))

    def test_command_output_is_private_and_single_json_record(self):
        self.prepared()
        output = StringIO()
        call_command("diagnose_report_dispatch", dry_run=True, stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result["outcome"], "ELIGIBLE")
        forbidden = (str(self.attempt.idempotency_key), self.attempt.request_sha256, self.plan.release_root,
            self.identity.session_key, self.grant.credentials.token, "Synthetic street", "Inspector",
            "snapshot", "author_identity", "dispatch_id", "storage_key", "bundle_sha256")
        for secret in forbidden:
            self.assertNotIn(secret, output.getvalue())

    def test_no_active_or_attempt_selection_options(self):
        for args in (("--active",), ("--attempt-id", str(uuid4()))):
            with self.assertRaises(CommandError):
                call_command("diagnose_report_dispatch", *args, stdout=StringIO(), stderr=StringIO())

    def test_database_failure_is_sanitized_and_has_structured_output(self):
        output = StringIO()
        with patch.object(dispatcher, "_read", side_effect=OperationalError("PRIVATE_CONNECTION_SECRET")):
            with self.assertRaisesMessage(CommandError, "dispatcher_database_unavailable"):
                call_command("diagnose_report_dispatch", stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result["outcome"], "UNAVAILABLE")
        self.assertNotIn("PRIVATE_CONNECTION_SECRET", output.getvalue())

    def test_evaluation_rejects_enclosing_transaction(self):
        with transaction.atomic():
            with self.assertRaisesMessage(dispatcher.DispatchDiagnosticError, "dispatcher_requires_autocommit"):
                dispatcher.evaluate()

    def test_two_observers_on_distinct_connections_do_not_mutate(self):
        self.prepared()
        before = self.stored()
        results = self.race(dispatcher.evaluate, dispatcher.evaluate)
        self.assertEqual([result["outcome"] for result in results], ["ELIGIBLE", "ELIGIBLE"])
        self.assertEqual(before, self.stored())

    def test_diagnostic_does_not_wait_on_slot_or_barrier_row_locks(self):
        self.prepared()
        self.move("DRAINING")
        with transaction.atomic():
            Slot.objects.select_for_update().get()
            Barrier.objects.select_for_update().get()
            future, _ = self.submit(dispatcher.evaluate)
            result = future.result(timeout=10)
            self.assertEqual(result["outcome"], "MAINTENANCE")

    def test_concurrent_deploy_close_between_reads_marks_result_stale(self):
        self.prepared()
        first_read, continue_read = Event(), Event()
        original = dispatcher._read

        def reads():
            data = original()
            if not first_read.is_set():
                first_read.set()
                if not continue_read.wait(timeout=10):
                    raise AssertionError("Concurrent transition did not complete")
            return data

        with patch.object(dispatcher, "_read", reads):
            future, _ = self.submit(dispatcher.evaluate)
            self.assertTrue(first_read.wait(timeout=10))
            self.move("DRAINING")
            continue_read.set()
            result = future.result(timeout=10)
        self.assertEqual(result["outcome"], "STALE")
        self.assertEqual(result["observed_outcome"], "ELIGIBLE")
        self.assertTrue(result["database_changed_during_observation"])
        self.assertFalse(result["eligible"])

    def test_postgresql_read_only_transaction_is_enforced(self):
        original = operations.barrier_status

        def attempted_write():
            Barrier.objects.create()
            return original()

        with patch.object(dispatcher, "barrier_status", attempted_write):
            with self.assertRaisesMessage(dispatcher.DispatchDiagnosticError, "dispatcher_database_unavailable"):
                dispatcher.evaluate()
        self.assertFalse(Barrier.objects.exists())
