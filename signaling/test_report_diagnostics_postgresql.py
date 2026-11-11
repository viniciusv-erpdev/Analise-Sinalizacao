"""PostgreSQL observations only; there is deliberately no recovery/kill API."""
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command, CommandError
from django.db import connection, transaction, OperationalError
from django.http import QueryDict
from django.test import TransactionTestCase, override_settings

from signaling import report_admission as admission, report_executor as executor, report_diagnostics as diagnostics
from signaling import test_reservation_concurrency as core
from signaling.models import (ReportFinalizationAttempt as Attempt, ReportPublicationSlot,
    WaypointReportDraft, ReportArtifact, ReportAnnualCounter, TechnicalReportVersion, TechnicalReport)
from signaling.report_snapshots import prepare_photos, canonical
from signaling.report_storage import PrivateReportStorage
from signaling.test_report_finalization import photo_upload


@skipUnless(connection.vendor == "postgresql", "Requires isolated real PostgreSQL")
class ReportDiagnosticsPostgreSQLTests(TransactionTestCase):
    reservation_permissions = ("view_signalingpoint", "generate_signaling_report", "finalize_technicalreport")
    acquire = core.PostgreSQLReservationConcurrencyTests.acquire
    submit = core.PostgreSQLReservationConcurrencyTests.submit
    race = core.PostgreSQLReservationConcurrencyTests.race

    def setUp(self):
        core.PostgreSQLReservationConcurrencyTests.setUp(self)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(REPORT_PRIVATE_ROOT=self.temp.name)
        override.enable()
        self.addCleanup(override.disable)

    def admit(self):
        WaypointReportDraft.objects.create(signaling_point=self.point,
            inspection_address="PRIVATE_ADDRESS_NOT_FOR_DIAGNOSTIC", inspection_date="2026-10-28",
            inspector_name="PRIVATE_INSPECTOR_NOT_FOR_DIAGNOSTIC")
        grant = self.acquire()
        self.token = grant.credentials.token
        self.key = uuid4()
        with override_settings(REPORT_ADMISSION_ENABLED=True):
            return admission.admit(point_id=self.point.pk, identity=self.identity,
                credentials=grant.credentials, user_id=self.client.session["_auth_user_id"], key=self.key,
                expected_revision=1, parameters=QueryDict(), photos=prepare_photos([photo_upload()]),
                analysis_state={"view_mode": "individual", "map_data": []})

    def stored(self):
        return canonical({model.__name__: list(model.objects.order_by("pk").values()) for model in
            (ReportPublicationSlot, Attempt, ReportArtifact, TechnicalReportVersion, TechnicalReport, ReportAnnualCounter)})

    def test_empty_slot_diagnostic_does_not_create_singleton(self):
        before = self.stored()
        result = diagnostics.diagnose()
        self.assertFalse(result["slot"]["exists"])
        self.assertIsNone(result["attempt"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(self.stored(), before)

    def test_admitted_diagnostic_preserves_every_record_and_file(self):
        attempt = self.admit()
        before = self.stored()
        keys = list(PrivateReportStorage().keys())
        contents = {key: Path(self.temp.name, key).read_bytes() for key in keys}
        statements = []
        def capture(execute, sql, params, many, context):
            statements.append(sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(capture):
            result = diagnostics.diagnose(verify_files=True)
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["attempt"]["id"], str(attempt.pk))
        self.assertEqual(result["artifacts"][0]["file_check"], "verified")
        self.assertFalse(result["database_changed_during_observation"])
        self.assertEqual(before, self.stored())
        self.assertEqual(contents, {key: Path(self.temp.name, key).read_bytes() for key in keys})
        self.assertEqual(sum("READ ONLY" in sql for sql in statements), 2)
        self.assertFalse(any("FOR UPDATE" in sql.upper() for sql in statements))
        self.assertFalse(any(sql.lstrip().upper().startswith(("UPDATE", "DELETE", "INSERT")) for sql in statements))

    def test_command_excludes_personal_fields_tokens_keys_paths_and_snapshot(self):
        attempt = self.admit()
        output = StringIO()
        call_command("diagnose_report_publication", attempt_id=attempt.pk, verify_files=True, stdout=output)
        text = output.getvalue()
        for forbidden in (self.temp.name, "PRIVATE_ADDRESS_NOT_FOR_DIAGNOSTIC",
                "PRIVATE_INSPECTOR_NOT_FOR_DIAGNOSTIC", self.token, str(self.key), self.identity.session_key,
                attempt.version.artifacts.get().storage_key, "author_identity", "snapshot", "request_sha256"):
            self.assertNotIn(forbidden, text)
        self.assertFalse(json.loads(text)["recovery"]["permitted"])

    def test_interrupted_or_failed_state_is_never_proof_of_termination(self):
        attempt = self.admit()
        for state in (Attempt.State.PROCESSING, Attempt.State.STORING, Attempt.State.INTERRUPTED, Attempt.State.FAILED):
            Attempt.objects.filter(pk=attempt.pk).update(state=state)
            before = self.stored()
            result = diagnostics.diagnose()
            self.assertEqual(result["recovery"]["termination_proof"], "unavailable")
            self.assertFalse(result["recovery"]["permitted"])
            self.assertEqual(result["recovery"]["executor_liveness"], "unknown")
            self.assertEqual(before, self.stored())

    def test_slot_epoch_mismatch_is_reported_without_repair(self):
        attempt = self.admit()
        ReportPublicationSlot.objects.filter(pk=1).update(execution_id=uuid4())
        before = self.stored()
        self.assertIn("slot_execution_mismatch", diagnostics.diagnose()["issues"])
        self.assertEqual(self.stored(), before)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, Attempt.State.ADMITTED)

    def test_empty_slot_with_unowned_admission_is_reported(self):
        self.admit()
        ReportPublicationSlot.objects.filter(pk=1).update(attempt=None, execution_id=None)
        before = self.stored()
        result = diagnostics.diagnose()
        self.assertIn("unfinished_admitted_attempt_without_slot", result["issues"])
        self.assertEqual(result["unowned_unfinished_attempts"]["count"], 1)
        self.assertEqual(self.stored(), before)

    def test_orphan_file_with_ambiguous_confirmation_is_counted_never_deleted(self):
        attempt = self.admit()
        storage = PrivateReportStorage()
        key = f"{attempt.version_id}/{attempt.execution_id}/{uuid4()}.pdf"
        storage.save(key, b"unregistered bytes")
        before = self.stored()
        result = diagnostics.diagnose()
        self.assertEqual(result["filesystem"]["unreferenced_files_in_version"], 1)
        self.assertIn("unreferenced_files_observed_not_safe_to_delete", result["issues"])
        self.assertIn(key, storage.keys())
        self.assertEqual(before, self.stored())

    def test_missing_and_corrupted_files_reported_without_changing_metadata(self):
        attempt = self.admit()
        artifact = attempt.version.artifacts.get()
        path = Path(self.temp.name, artifact.storage_key)
        data = path.read_bytes()
        path.write_bytes(bytes(byte ^ 1 for byte in data))  # Same size, different hash.
        self.assertEqual(diagnostics.diagnose()["artifacts"][0]["file_check"], "size_ok_hash_not_checked")
        self.assertEqual(diagnostics.diagnose(verify_files=True)["artifacts"][0]["file_check"], "integrity_or_path_unavailable")
        # Disposable fixture only; the command itself never deletes files.
        path.unlink()
        self.assertEqual(diagnostics.diagnose()["artifacts"][0]["file_check"], "missing")
        self.assertTrue(ReportArtifact.objects.filter(pk=artifact.pk).exists())

    def test_snapshot_corruption_is_reported_without_exposing_contents(self):
        attempt = self.admit()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE signaling_technicalreportversion SET snapshot = %s WHERE id = %s",
                           [json.dumps({"private": "DO_NOT_EXPOSE"}), attempt.version_id])
        result = diagnostics.diagnose()
        self.assertIn("snapshot_integrity_failed", result["issues"])
        self.assertNotIn("DO_NOT_EXPOSE", json.dumps(result))

    def test_diagnostic_does_not_wait_for_executor_row_locks(self):
        attempt = self.admit()
        with transaction.atomic():
            ReportPublicationSlot.objects.select_for_update().get(pk=1)
            Attempt.objects.select_for_update().get(pk=attempt.pk)
            future, _ = self.submit(diagnostics.diagnose)
            result = future.result(timeout=8)
            self.assertEqual(result["attempt"]["id"], str(attempt.pk))
        self.assertFalse(result["recovery"]["permitted"])

    def test_simultaneous_administrators_observe_without_rotating_fencing(self):
        self.admit()
        before = self.stored()
        results = self.race(diagnostics.diagnose, diagnostics.diagnose)
        self.assertTrue(all(not result["recovery"]["permitted"] for result in results))
        self.assertEqual(self.stored(), before)

    def test_database_change_during_file_check_is_explicitly_reported(self):
        attempt = self.admit()
        entered, finish = Event(), Event()
        check = diagnostics._file_check
        def pause(*args):
            entered.set()
            if not finish.wait(8):
                raise AssertionError("Concurrent executor was blocked")
            return check(*args)
        with patch.object(diagnostics, "_file_check", side_effect=pause):
            future, _ = self.submit(diagnostics.diagnose)
            try:
                self.assertTrue(entered.wait(5))
                with override_settings(REPORT_EXECUTOR_ENABLED=True):
                    claimed = executor.claim(attempt.pk)
            finally:
                finish.set()
            result = future.result(timeout=10)
        self.assertTrue(result["database_changed_during_observation"])
        self.assertNotEqual(claimed.execution_id, attempt.execution_id)

    def test_database_failure_is_sanitized_and_does_not_change_slot(self):
        self.admit()
        before = self.stored()
        with patch.object(diagnostics, "_metadata", side_effect=OperationalError("SECRET_PATH")):
            with self.assertRaisesMessage(CommandError, "diagnostic_database_unavailable"):
                call_command("diagnose_report_publication", stdout=StringIO())
        self.assertEqual(before, self.stored())

    def test_no_recovery_or_human_boolean_option_is_available(self):
        self.admit()
        before = self.stored()
        from signaling.management.commands.diagnose_report_publication import Command
        parser = Command().create_parser("manage.py", "diagnose_report_publication")
        options = {option for action in parser._actions for option in action.option_strings}
        self.assertFalse(options & {"--recover", "--unlock", "--force", "--confirm-terminated"})
        self.assertEqual(before, self.stored())
