"""Independent executor: real PostgreSQL, real renderer/converter on success.

Only fault scenarios substitute pipeline components. Concurrency uses independent
connections, and abrupt termination is exercised with a real child process.
"""
from contextlib import contextmanager
from io import BytesIO, StringIO
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management import call_command, CommandError
from django.db import connection, connections, transaction, OperationalError
from django.http import QueryDict
from django.test import TransactionTestCase, override_settings

from signaling import report_executor as executor, report_admission as admission
from signaling import report_finalization as legacy, reservations
from signaling import test_reservation_concurrency as core
from signaling.models import ReportFinalizationAttempt as Attempt, ReportPublicationSlot, WaypointReportDraft, ReportAnnualCounter
from signaling.pdf_conversion import find_libreoffice, PDFConversionError
from signaling.report_snapshots import prepare_photos, canonical
from signaling.report_storage import PrivateReportStorage, ArtifactStorageError
from signaling.test_report_finalization import photo_upload

try:
    LIBREOFFICE = find_libreoffice(os.environ.get("LIBREOFFICE_EXECUTABLE"))
    import pypdf
    REAL_CONVERSION = True
except (PDFConversionError, ImportError):
    LIBREOFFICE, REAL_CONVERSION = None, False


@skipUnless(connection.vendor == "postgresql", "Requires isolated real PostgreSQL")
@override_settings(REPORT_ADMISSION_ENABLED=True, REPORT_EXECUTOR_ENABLED=True)
class ReportExecutorPostgreSQLTests(TransactionTestCase):
    reservation_permissions = ("view_signalingpoint", "generate_signaling_report", "finalize_technicalreport")
    acquire = core.PostgreSQLReservationConcurrencyTests.acquire
    release = core.PostgreSQLReservationConcurrencyTests.release
    submit = core.PostgreSQLReservationConcurrencyTests.submit
    race = core.PostgreSQLReservationConcurrencyTests.race

    def setUp(self):
        core.PostgreSQLReservationConcurrencyTests.setUp(self)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(REPORT_PRIVATE_ROOT=self.temp.name, REPORT_LIBREOFFICE_EXECUTABLE=LIBREOFFICE)
        override.enable()
        self.addCleanup(override.disable)
        WaypointReportDraft.objects.create(signaling_point=self.point,
            inspection_address="Executor synthetic street", inspection_date="2026-10-28",
            inspector_name="Inspector", technical_analysis="Frozen technical conclusion")
        self.grant = self.acquire()
        self.photos = prepare_photos([photo_upload()])
        self.attempt = admission.admit(point_id=self.point.pk, identity=self.identity,
            credentials=self.grant.credentials, user_id=self.client.session["_auth_user_id"],
            key=uuid4(), expected_revision=1, parameters=QueryDict(),
            analysis_state={"view_mode": "individual", "map_data": [], "analysis_id": "executor"},
            photos=self.photos)

    def error(self, code, operation):
        with self.assertRaises(executor.ExecutionError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def assert_retained(self, state):
        current = Attempt.objects.select_related("version__report").get(pk=self.attempt.pk)
        self.assertEqual(current.state, state)
        self.assertIsNone(current.version.finalized_at)
        self.assertIsNone(current.version.report.number_assigned_at)
        slot = ReportPublicationSlot.objects.get()
        self.assertEqual(slot.attempt_id, current.pk)
        self.assertEqual(slot.execution_id, current.execution_id)
        return current

    @skipUnless(REAL_CONVERSION, "Requires real LibreOffice and pypdf")
    def test_success_real_pipeline_without_session_reservation_or_mutable_waypoint(self):
        frozen = canonical(self.attempt.version.snapshot)
        number = self.attempt.version.report.official_number
        original_execution = self.attempt.execution_id
        self.release(self.grant)
        Session.objects.filter(session_key=self.identity.session_key).delete()
        # Freeze means subsequent waypoint edits do not revoke admitted content.
        WaypointReportDraft.objects.filter(signaling_point=self.point).update(technical_analysis="Changed after admission")
        with override_settings(REPORT_ADMISSION_ENABLED=False):
            result = executor.execute(self.attempt.pk)
        self.assertEqual(result.state, Attempt.State.FINALIZED)
        self.assertNotEqual(result.execution_id, original_execution)
        self.assertEqual(canonical(result.version.snapshot), frozen)
        self.assertEqual(result.version.report.official_number, number)
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)
        self.assertEqual(result.version.finalized_at, result.version.report.number_assigned_at)
        self.assertIsNone(ReportPublicationSlot.objects.get().attempt_id)
        artifacts = list(result.version.artifacts.order_by("kind"))
        self.assertEqual([a.kind for a in artifacts], ["DOCX", "PDF", "PHOTO"])
        pdf = PrivateReportStorage().read(result.version.artifacts.get(kind="PDF"))
        content = " ".join((page.extract_text() or "") for page in pypdf.PdfReader(BytesIO(pdf)).pages)
        self.assertIn(number, content)
        self.assertIn("Frozen technical conclusion", content)
        replay = executor.execute(self.attempt.pk)
        self.assertEqual(replay.execution_id, result.execution_id)
        self.assertEqual(list(replay.version.artifacts.values_list("pk", flat=True)), [a.pk for a in result.version.artifacts.all()])

    def test_two_executors_claim_using_distinct_connections_only_one_starts(self):
        def claim():
            try:
                return executor.claim(self.attempt.pk)
            except executor.ExecutionError as error:
                return error.code
        results = self.race(claim, claim)
        self.assertEqual(sum(isinstance(item, Attempt) for item in results), 1)
        self.assertTrue(any(item in ("publication_busy", "execution_already_started") for item in results if isinstance(item, str)))
        current = self.assert_retained(Attempt.State.PROCESSING)
        self.assertNotEqual(current.execution_id, self.attempt.execution_id)

    @skipUnless(REAL_CONVERSION, "Requires real LibreOffice and pypdf")
    def test_two_full_executors_cannot_duplicate_publication(self):
        def run():
            try:
                return executor.execute(self.attempt.pk)
            except executor.ExecutionError as error:
                return error.code
        # Reservation races use a 12s helper. Real conversion has its own 60s
        # supervisor; allow that bound plus rendering/storage overhead here.
        barrier = Barrier(3)
        first, pid1 = self.submit(run, barrier)
        second, pid2 = self.submit(run, barrier)
        self.assertNotEqual(pid1, pid2)
        barrier.wait(timeout=10)
        results = first.result(timeout=90), second.result(timeout=90)
        self.assertTrue(any(isinstance(item, Attempt) and item.state == "FINALIZED" for item in results))
        self.assertEqual(self.attempt.version.artifacts.filter(kind="PDF").count(), 1)
        self.assertEqual(self.attempt.version.artifacts.filter(kind="DOCX").count(), 1)
        self.assertIsNone(ReportPublicationSlot.objects.get().attempt_id)

    def test_missing_slot_ownership_never_starts(self):
        ReportPublicationSlot.objects.filter(pk=1).update(attempt=None, execution_id=None)
        self.error("execution_not_slot_owner", lambda: executor.execute(self.attempt.pk))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.state, Attempt.State.ADMITTED)
        self.assertFalse(self.attempt.version.artifacts.filter(kind__in=("DOCX", "PDF")).exists())

    def test_mismatched_execution_id_is_rejected(self):
        ReportPublicationSlot.objects.filter(pk=1).update(execution_id=uuid4())
        self.error("execution_superseded", lambda: executor.execute(self.attempt.pk))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.state, Attempt.State.ADMITTED)

    def test_generation_failure_retains_slot(self):
        with patch.object(executor, "render_snapshot", side_effect=RuntimeError("private details")):
            self.error("execution_failed", lambda: executor.execute(self.attempt.pk))
        self.assert_retained(Attempt.State.FAILED)
        self.error("admission_reconciliation_required", lambda: executor.execute(self.attempt.pk))

    def test_converter_timeout_retains_snapshot_number_and_slot(self):
        frozen = canonical(self.attempt.version.snapshot)
        with patch.object(executor, "convert_docx_to_pdf", side_effect=PDFConversionError("conversion_timeout")):
            self.error("conversion_timeout", lambda: executor.execute(self.attempt.pk))
        current = self.assert_retained(Attempt.State.FAILED)
        self.assertEqual(canonical(current.version.snapshot), frozen)
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)

    @skipUnless(REAL_CONVERSION, "Requires pypdf validation dependency")
    def test_invalid_pdf_is_never_published(self):
        with patch.object(executor, "convert_docx_to_pdf", return_value=b"invalid PDF"):
            self.error("invalid_pdf", lambda: executor.execute(self.attempt.pk))
        self.assert_retained(Attempt.State.FAILED)

    @skipUnless(REAL_CONVERSION, "Requires real LibreOffice and pypdf")
    def test_storage_failure_retains_slot_and_originals(self):
        with patch.object(PrivateReportStorage, "save", side_effect=ArtifactStorageError("disk failure")):
            self.error("execution_storage_failed", lambda: executor.execute(self.attempt.pk))
        current = self.assert_retained(Attempt.State.FAILED)
        self.assertEqual(PrivateReportStorage().read(current.version.artifacts.get(kind="PHOTO")), self.photos[0][1])

    def test_keyboard_interruption_is_recoverable_but_not_automatically_retried(self):
        with patch.object(executor, "convert_docx_to_pdf", side_effect=KeyboardInterrupt()):
            self.error("execution_interrupted", lambda: executor.execute(self.attempt.pk))
        self.assert_retained(Attempt.State.INTERRUPTED)
        self.error("admission_reconciliation_required", lambda: executor.execute(self.attempt.pk))

    def test_command_sigterm_preserves_slot_and_restores_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        with patch.object(executor, "render_snapshot", side_effect=lambda *args: signal.raise_signal(signal.SIGTERM)):
            with self.assertRaisesMessage(CommandError, "execution_interrupted"):
                call_command("execute_admitted_report", attempt_id=self.attempt.pk, stdout=StringIO(), stderr=StringIO())
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        self.assert_retained(Attempt.State.INTERRUPTED)

    def test_real_child_process_exit_after_claim_keeps_slot(self):
        env = dict(os.environ, DJANGO_SETTINGS_MODULE="config.settings", DJANGO_DB_BACKEND="postgresql",
            POSTGRES_DB=str(connection.settings_dict["NAME"]), POSTGRES_USER=str(connection.settings_dict["USER"]),
            POSTGRES_PASSWORD=str(connection.settings_dict["PASSWORD"]), POSTGRES_HOST=str(connection.settings_dict["HOST"]),
            POSTGRES_PORT=str(connection.settings_dict["PORT"]), REPORT_EXECUTOR_ENABLED="true",
            DJANGO_TEST_DB_NAME=f"{connection.settings_dict['NAME']}_child_unused")
        script = ("import os, django; django.setup(); from uuid import UUID; "
                  "from signaling.report_executor import claim; "
                  f"claim(UUID('{self.attempt.pk}')); os._exit(73)")
        result = subprocess.run([sys.executable, "-B", "-c", script], env=env, cwd=settings.BASE_DIR,
            capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.assertEqual(result.returncode, 73)
        self.assert_retained(Attempt.State.PROCESSING)
        self.error("execution_already_started", lambda: executor.execute(self.attempt.pk))

    def test_old_execution_cannot_commit_after_execution_id_changes(self):
        render = executor.render_snapshot
        replacement = uuid4()
        def supersede(snapshot, photos):
            docx = render(snapshot, photos)
            with admission.coordination() as slot:
                Attempt.objects.filter(pk=self.attempt.pk).update(execution_id=replacement)
                slot.execution_id = replacement
                slot.save(update_fields=["execution_id"])
            return docx
        with patch.object(executor, "render_snapshot", side_effect=supersede):
            self.error("execution_superseded", lambda: executor.execute(self.attempt.pk))
        current = self.assert_retained(Attempt.State.PROCESSING)
        self.assertEqual(current.execution_id, replacement)
        self.assertEqual(current.error_code, "")

    @skipUnless(REAL_CONVERSION, "Requires real LibreOffice and pypdf")
    def test_fencing_immediately_before_final_commit_prevents_publication(self):
        complete = executor._complete
        replacement = uuid4()
        def supersede(attempt, artifacts):
            with admission.coordination() as slot:
                Attempt.objects.filter(pk=attempt.pk).update(execution_id=replacement)
                slot.execution_id = replacement
                slot.save(update_fields=["execution_id"])
            return complete(attempt, artifacts)
        with patch.object(executor, "_complete", side_effect=supersede):
            self.error("execution_superseded", lambda: executor.execute(self.attempt.pk))
        current = self.assert_retained(Attempt.State.STORING)
        self.assertEqual(current.execution_id, replacement)
        self.assertEqual(current.error_code, "")

    def test_database_connection_loss_keeps_ambiguous_execution(self):
        render = executor.render_snapshot
        def disconnect(snapshot, photos):
            docx = render(snapshot, photos)
            connection.connection.close()  # Actual psycopg connection loss, no mocked SQL/locks.
            return docx
        try:
            with patch.object(executor, "render_snapshot", side_effect=disconnect):
                self.error("execution_database_state_unknown", lambda: executor.execute(self.attempt.pk))
        finally:
            connections.close_all()
        self.assert_retained(Attempt.State.PROCESSING)

    @skipUnless(REAL_CONVERSION, "Requires real LibreOffice and pypdf")
    def test_final_commit_rollback_never_releases_slot_or_partially_publishes(self):
        save = ReportPublicationSlot.save
        def fail_release(slot, *args, **kwargs):
            save(slot, *args, **kwargs)
            if slot.attempt_id is None:
                raise OperationalError("injected transaction failure")
        with patch.object(ReportPublicationSlot, "save", fail_release):
            self.error("execution_database_state_unknown", lambda: executor.execute(self.attempt.pk))
        self.assert_retained(Attempt.State.STORING)
        self.error("execution_already_started", lambda: executor.execute(self.attempt.pk))

    @skipUnless(REAL_CONVERSION, "Requires real LibreOffice and pypdf")
    def test_lost_final_commit_ack_does_not_downgrade_or_republish(self):
        coordinate = admission.coordination
        @contextmanager
        def lost_ack():
            with coordinate() as slot:
                yield slot
            if slot.attempt_id is None:
                raise OperationalError("lost acknowledgement after actual commit")
        with patch.object(admission, "coordination", lost_ack):
            self.error("execution_database_state_unknown", lambda: executor.execute(self.attempt.pk))
        current = Attempt.objects.get(pk=self.attempt.pk)
        self.assertEqual(current.state, Attempt.State.FINALIZED)
        self.assertIsNone(ReportPublicationSlot.objects.get().attempt_id)
        self.assertEqual(executor.execute(self.attempt.pk).execution_id, current.execution_id)

    @skipUnless(REAL_CONVERSION, "Requires real LibreOffice and pypdf")
    def test_successful_command_discovery_and_empty_slot(self):
        output = StringIO()
        call_command("execute_admitted_report", stdout=output)
        self.assertIn(f"FINALIZED {self.attempt.pk}", output.getvalue())
        output = StringIO()
        call_command("execute_admitted_report", stdout=output)
        self.assertEqual(output.getvalue().strip(), "no_admitted_report")

    @override_settings(REPORT_EXECUTOR_ENABLED=False)
    def test_executor_disabled_gate_does_not_claim(self):
        self.error("executor_disabled", lambda: executor.execute(self.attempt.pk))
        self.assert_retained(Attempt.State.ADMITTED)

    def test_execution_rejects_ambient_transaction(self):
        with transaction.atomic():
            self.error("executor_requires_autocommit", lambda: executor.execute(self.attempt.pk))
        self.assert_retained(Attempt.State.ADMITTED)
