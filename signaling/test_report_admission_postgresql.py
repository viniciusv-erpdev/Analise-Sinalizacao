"""Real isolated PostgreSQL transactions/connections; no mocked locking."""
from datetime import timedelta
from contextlib import contextmanager
from io import StringIO
import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.sessions.models import Session
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, connections, transaction, IntegrityError, OperationalError
from django.http import QueryDict
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from signaling import report_admission as service, report_finalization as legacy, reservations as r
from signaling.models import (SignalingPoint, WaypointReportDraft, TechnicalReport,
    ReportFinalizationAttempt as Attempt, ReportAnnualCounter, ReportArtifact, ReportPublicationSlot)
from signaling.report_snapshots import prepare_photos
from signaling.report_storage import PrivateReportStorage, ArtifactStorageError
from signaling.test_pdf_conversion import fake_pdf
from signaling.test_report_finalization import photo_upload
from signaling import test_reservation_concurrency as core


@skipUnless(connection.vendor == "postgresql", "Requires isolated real PostgreSQL")
@override_settings(REPORT_ADMISSION_ENABLED=True, REPORT_FINALIZATION_ENABLED=True)
class ReportAdmissionPostgreSQLTests(TransactionTestCase):
    reservation_permissions = ("view_signalingpoint", "generate_signaling_report", "finalize_technicalreport")
    acquire = core.PostgreSQLReservationConcurrencyTests.acquire
    release = core.PostgreSQLReservationConcurrencyTests.release
    submit = core.PostgreSQLReservationConcurrencyTests.submit
    race = core.PostgreSQLReservationConcurrencyTests.race

    def setUp(self):
        core.PostgreSQLReservationConcurrencyTests.setUp(self)
        self.user_id = self.client.session["_auth_user_id"]
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(REPORT_PRIVATE_ROOT=self.temp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.make_draft(self.point)
        self.grant = self.acquire()
        self.key = uuid4()
        self.analysis = {"view_mode": "individual", "analysis_id": "synthetic", "map_data": []}
        for name in ("render_snapshot", "convert_docx_to_pdf"):
            mocked = patch.object(legacy, name, side_effect=AssertionError("Admission must not render"))
            mocked.start()
            self.addCleanup(mocked.stop)

    def make_draft(self, point):
        return WaypointReportDraft.objects.create(signaling_point=point,
            inspection_address="Synthetic street", inspection_date="2026-10-28", inspector_name="Inspector")

    def arguments(self, **changes):
        return dict(point_id=self.point.pk, identity=self.identity, credentials=self.grant.credentials,
            user_id=self.user_id, key=self.key, expected_revision=1, parameters=QueryDict(),
            analysis_state=self.analysis, photos=[]) | changes

    def admit(self, **changes):
        return service.admit(**self.arguments(**changes))

    def outcome(self, operation):
        try:
            return operation()
        except legacy.FinalizationError as error:
            return error.code

    def assert_error(self, code, operation):
        with self.assertRaises(legacy.FinalizationError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def test_different_points_on_distinct_connections_only_one_admitted(self):
        other = SignalingPoint.objects.create(latitude=1, longitude=1, status="OK")
        self.make_draft(other)
        grant = r.acquire_reservation(point_id=other.pk, identity=self.identity, interaction_id=uuid4())
        first, second = self.race(lambda: self.outcome(self.admit), lambda: self.outcome(
            lambda: self.admit(point_id=other.pk, credentials=grant.credentials, key=uuid4())))
        self.assertEqual(sum(isinstance(item, Attempt) for item in (first, second)), 1)
        self.assertIn("publication_busy", (first, second))
        self.assertEqual(TechnicalReport.objects.count(), 1)
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)
        self.assertEqual(ReportPublicationSlot.objects.exclude(attempt=None).count(), 1)

    def test_second_intention_busy_without_number_or_artifacts(self):
        self.admit()
        before = list(ReportAnnualCounter.objects.values_list("year", "last_reserved"))
        self.assert_error("publication_busy", lambda: self.admit(key=uuid4(), photos=prepare_photos([photo_upload()])))
        self.assertEqual(list(ReportAnnualCounter.objects.values_list("year", "last_reserved")), before)
        self.assertFalse(ReportArtifact.objects.exists())
        self.assertEqual(list(PrivateReportStorage().keys()), [])

    def test_inflight_mutex_rejects_without_waiting_for_first_commit(self):
        entered, finish = Event(), Event()
        def holder():
            with service.coordination():
                entered.set()
                if not finish.wait(8):
                    raise AssertionError("Contender blocked instead of returning busy")
        future, _ = self.submit(holder)
        try:
            self.assertTrue(entered.wait(5))
            self.assert_error("publication_busy", self.admit)
            self.assertFalse(TechnicalReport.objects.exists())
        finally:
            finish.set()
        future.result(timeout=10)

    def test_same_key_replays_even_without_reservation_or_analysis(self):
        attempt = self.admit()
        self.release(self.grant)
        replay = self.admit(credentials=None, analysis_state=None)
        self.assertEqual(replay.pk, attempt.pk)
        self.assertEqual(Attempt.objects.count(), 1)
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)

    def test_same_key_different_fingerprint_rejected_before_busy(self):
        self.admit()
        self.assert_error("idempotency_key_conflict", lambda: self.admit(expected_revision=2))

    def test_same_key_concurrent_replay_creates_one_intention(self):
        results = self.race(lambda: self.outcome(self.admit), lambda: self.outcome(self.admit))
        # While the first commit is unknown, a nonblocking call may say busy.
        attempt = next(item for item in results if isinstance(item, Attempt))
        self.assertEqual(self.admit().pk, attempt.pk)
        self.assertEqual(Attempt.objects.count(), 1)

    def test_release_logout_and_reimport_connection_do_not_lose_inputs(self):
        photos = prepare_photos([photo_upload()])
        attempt = self.admit(photos=photos)
        self.release(self.grant)
        Session.objects.filter(session_key=self.identity.session_key).delete()
        # Simulate losing all HTTP state and connection, not an executor start.
        attempt_id, execution_id = attempt.pk, attempt.execution_id
        self.analysis.clear()
        connections.close_all()
        fresh = importlib.reload(service)
        snapshot, originals = fresh.load_inputs(attempt_id=attempt_id, execution_id=execution_id)
        self.assertEqual(originals, [photos[0][1]])
        self.assertEqual(snapshot["official_number"], attempt.version.report.official_number)
        self.assertEqual(snapshot["author"]["id"], int(self.user_id))
        self.assertEqual(Attempt.objects.get(pk=attempt_id).state, Attempt.State.ADMITTED)

    def test_failure_after_file_write_rolls_back_slot_attempt_and_counter_keeps_orphan(self):
        photos = prepare_photos([photo_upload()])
        with patch.object(PrivateReportStorage, "read", side_effect=ArtifactStorageError("injected")):
            with self.assertRaises(ArtifactStorageError):
                self.admit(photos=photos)
        self.assertFalse(Attempt.objects.exists())
        self.assertFalse(ReportPublicationSlot.objects.filter(attempt__isnull=False).exists())
        self.assertFalse(ReportAnnualCounter.objects.exists())
        orphan = list(PrivateReportStorage().keys())
        self.assertEqual(len(orphan), 1)
        self.assertEqual(self.admit(photos=photos).state, Attempt.State.ADMITTED)
        self.assertIn(orphan[0], PrivateReportStorage().keys())

    def test_lost_commit_acknowledgement_preserves_slot_files_and_replay(self):
        coordinate = service.coordination
        @contextmanager
        def lost_ack():
            with coordinate() as slot:
                yield slot
            raise OperationalError("simulated acknowledgement loss after real commit")
        photos = prepare_photos([photo_upload()])
        with patch.object(service, "coordination", lost_ack):
            with self.assertRaises(OperationalError):
                self.admit(photos=photos)
        attempt = Attempt.objects.get()
        self.assertEqual(self.admit(photos=photos).pk, attempt.pk)
        self.assertEqual(ReportPublicationSlot.objects.get().attempt_id, attempt.pk)
        self.assertEqual(service.load_inputs(attempt_id=attempt.pk,
            execution_id=attempt.execution_id)[1], [photos[0][1]])

    def test_failure_after_slot_write_rolls_back_every_database_record(self):
        save = ReportPublicationSlot.save
        def fail_after_save(slot, *args, **kwargs):
            save(slot, *args, **kwargs)
            if slot.attempt_id:
                raise RuntimeError("injected before commit")
        with patch.object(ReportPublicationSlot, "save", fail_after_save):
            with self.assertRaises(RuntimeError):
                self.admit(photos=prepare_photos([photo_upload()]))
        self.assertFalse(Attempt.objects.exists())
        self.assertFalse(ReportAnnualCounter.objects.exists())
        self.assertFalse(ReportPublicationSlot.objects.filter(attempt__isnull=False).exists())
        self.assertEqual(self.admit().state, Attempt.State.ADMITTED)

    def test_invalid_revision_and_metadata_do_not_claim_slot(self):
        self.assert_error("draft_revision_conflict", lambda: self.admit(expected_revision=3))
        photos = prepare_photos([photo_upload()])
        photos[0][0]["sha256"] = "0" * 64
        with self.assertRaises(ValidationError):
            self.admit(photos=photos)
        self.assertFalse(TechnicalReport.objects.exists())
        self.assertFalse(ReportPublicationSlot.objects.filter(attempt__isnull=False).exists())

    def test_authentication_permission_and_reservation_required_before_admission(self):
        with self.assertRaises(r.ReservationAuthenticationRequired):
            self.admit(identity=r.ReservationIdentity("missing-session"))
        actor = get_user_model().objects.get(pk=self.user_id)
        permission = Permission.objects.get(codename="finalize_technicalreport")
        actor.user_permissions.remove(permission)
        with self.assertRaises(r.ReservationPermissionDenied):
            self.admit()
        actor.user_permissions.add(permission)
        self.release(self.grant)
        with self.assertRaises(r.ReservationInactive):
            self.admit()
        self.assertFalse(TechnicalReport.objects.exists())
        self.assertFalse(ReportPublicationSlot.objects.filter(attempt__isnull=False).exists())

    def test_snapshot_and_photo_tampering_are_detected_on_reload(self):
        attempt = self.admit(photos=prepare_photos([photo_upload()]))
        artifact = attempt.version.artifacts.get()
        Path(self.temp.name, artifact.storage_key).write_bytes(b"corrupt")
        with self.assertRaises(ArtifactStorageError):
            service.load_inputs(attempt_id=attempt.pk, execution_id=attempt.execution_id)
        self.assertEqual(Attempt.objects.get(pk=attempt.pk).state, Attempt.State.ADMITTED)

    def test_old_execution_cannot_commit_result_after_fencing(self):
        attempt = self.admit()
        old_id, new_id = attempt.execution_id, uuid4()
        # Simulates the future supervised recovery AFTER establishing termination.
        with service.coordination() as slot:
            Attempt.objects.filter(pk=attempt.pk).update(execution_id=new_id, state="PROCESSING")
            slot.execution_id = new_id
            slot.save(update_fields=["execution_id"])
        with transaction.atomic():
            self.assert_error("execution_superseded", lambda: service.assert_execution(attempt.pk, old_id))
            current = service.assert_execution(attempt.pk, new_id)
            self.assertIsNone(current.version.finalized_at)
        self.assert_error("execution_requires_transaction", lambda: service.assert_execution(attempt.pk, new_id))

    def test_slot_mismatch_and_corrupt_snapshot_reject_execution(self):
        attempt = self.admit()
        with transaction.atomic():
            self.assert_error("execution_superseded", lambda: service.assert_execution(attempt.pk, uuid4()))
        # A corrupt artifact is detected before any executor can use originals.
        photos = attempt.version.snapshot
        photos["author"]["username"] = "changed"
        # Bypass application immutability to simulate corruption at the DB boundary.
        with connection.cursor() as cursor:
            import json
            cursor.execute("UPDATE signaling_technicalreportversion SET snapshot = %s WHERE id = %s",
                           [json.dumps(photos), attempt.version_id])
        self.assert_error("snapshot_integrity_failed", lambda: service.load_inputs(
            attempt_id=attempt.pk, execution_id=attempt.execution_id))

    def test_retry_is_idempotent_and_never_reclaims_failed_or_overdue_slot(self):
        attempt = self.admit()
        self.release(self.grant)
        self.assertEqual(service.retry_admission(attempt_id=attempt.pk, user_id=self.user_id).pk, attempt.pk)
        Attempt.objects.filter(pk=attempt.pk).update(state="FAILED", deadline=timezone.now()-timedelta(days=1))
        self.assert_error("admission_reconciliation_required", lambda: service.retry_admission(
            attempt_id=attempt.pk, user_id=self.user_id))
        self.assert_error("publication_busy", lambda: self.admit(key=uuid4()))
        self.assertEqual(ReportPublicationSlot.objects.get().attempt_id, attempt.pk)

    def test_legacy_and_its_retry_cannot_bypass_occupied_slot_even_if_flag_turned_off(self):
        attempt = self.admit()
        with override_settings(REPORT_ADMISSION_ENABLED=False):
            self.assert_error("publication_busy", lambda: legacy.finalize(**self.arguments(key=uuid4())))
            self.assert_error("publication_busy", lambda: legacy.retry(attempt_id=attempt.pk,
                user_id=self.user_id, identity=self.identity, credentials=self.grant.credentials))
        from signaling.report_finalization_views import response
        self.assertEqual(response(attempt).status_code, 409)

    def test_legacy_disabled_in_admission_mode_without_claiming_slot(self):
        self.assert_error("synchronous_finalization_disabled", lambda: legacy.finalize(**self.arguments()))
        self.assertFalse(Attempt.objects.exists())

    def test_retry_of_different_failed_intention_is_busy(self):
        with override_settings(REPORT_ADMISSION_ENABLED=False), patch.object(
                legacy, "render_snapshot", side_effect=RuntimeError("failed before conversion")):
            self.assert_error("finalization_failed", lambda: legacy.finalize(**self.arguments()))
        failed = Attempt.objects.get()
        self.admit(key=uuid4())
        self.assert_error("publication_busy", lambda: service.retry_admission(
            attempt_id=failed.pk, user_id=self.user_id))
        self.assert_error("publication_busy", lambda: legacy.retry(attempt_id=failed.pk,
            user_id=self.user_id, identity=self.identity, credentials=self.grant.credentials))

    @override_settings(REPORT_ADMISSION_ENABLED=False)
    def test_internal_admission_disabled_by_default_gate(self):
        self.assert_error("admission_disabled", self.admit)
        self.assertFalse(Attempt.objects.exists())

    @override_settings(REPORT_ADMISSION_ENABLED=False)
    def test_legacy_still_runs_synchronously_when_new_gate_disabled(self):
        with patch.object(legacy, "render_snapshot", return_value=b"docx"), patch.object(
                legacy, "convert_docx_to_pdf", return_value=fake_pdf()):
            attempt = legacy.finalize(**self.arguments())
        self.assertEqual(attempt.state, Attempt.State.FINALIZED)
        self.assertIsNone(attempt.admitted_at)
        self.assertIsNone(ReportPublicationSlot.objects.get().attempt_id)

    def test_reconciliation_never_expires_slot_or_deletes_its_inputs(self):
        attempt = self.admit(photos=prepare_photos([photo_upload()]))
        Attempt.objects.filter(pk=attempt.pk).update(state="PROCESSING", deadline=timezone.now()-timedelta(days=2))
        storage = PrivateReportStorage()
        key = f"{attempt.version_id}/{attempt.execution_id}/{uuid4()}.pdf"
        storage.save(key, b"unregistered")
        old = (timezone.now()-timedelta(days=2)).timestamp()
        os.utime(Path(self.temp.name, key), (old, old))
        call_command("reconcile_report_finalizations", mark_interrupted=True, delete_orphans=True, stdout=StringIO())
        self.assertIn(key, storage.keys())
        self.assertEqual(Attempt.objects.get(pk=attempt.pk).state, "PROCESSING")
        self.assertEqual(ReportPublicationSlot.objects.get().attempt_id, attempt.pk)

    def test_reconciliation_does_not_delete_an_uncommitted_admission_file(self):
        entered, finish = Event(), Event()
        original_read = PrivateReportStorage.read
        def blocked_read(storage, artifact):
            old = (timezone.now()-timedelta(days=2)).timestamp()
            os.utime(Path(self.temp.name, artifact.storage_key), (old, old))
            entered.set()
            if not finish.wait(8):
                raise AssertionError("Cleanup blocked on in-flight admission")
            return original_read(storage, artifact)
        with patch.object(PrivateReportStorage, "read", blocked_read):
            future, _ = self.submit(lambda: self.admit(photos=prepare_photos([photo_upload()])))
            try:
                self.assertTrue(entered.wait(5))
                call_command("reconcile_report_finalizations", delete_orphans=True, stdout=StringIO())
                self.assertEqual(len(list(PrivateReportStorage().keys())), 1)
            finally:
                finish.set()
            attempt = future.result(timeout=10)
        self.assertEqual(service.load_inputs(attempt_id=attempt.pk,
            execution_id=attempt.execution_id)[1], [prepare_photos([photo_upload()])[0][1]])

    def test_singleton_and_owner_constraints_are_real_database_constraints(self):
        attempt = self.admit()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReportPublicationSlot.objects.create(pk=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReportPublicationSlot.objects.filter(pk=1).update(execution_id=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attempt.objects.filter(pk=attempt.pk).update(admitted_at=None)
