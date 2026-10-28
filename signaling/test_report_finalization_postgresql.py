"""Real PostgreSQL finalization/numbering/idempotency/recovery tests.

Conversion is simulated to exercise transactional boundaries deterministically.
LibreOffice itself remains covered separately by test_pdf_integration.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from tempfile import TemporaryDirectory
from threading import Event
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from signaling import reservations as r, report_finalization as service
from signaling.models import (SignalingPoint, WaypointReportDraft, WaypointReservation,
    TechnicalReport, TechnicalReportVersion, ReportArtifact, ReportFinalizationAttempt as Attempt,
    ReportAnnualCounter, SignalingIntervention)
from signaling.report_snapshots import prepare_photos, digest, render_snapshot
from signaling.report_storage import PrivateReportStorage, ArtifactStorageError
from signaling.pdf_conversion import PDFConversionError
from signaling.test_pdf_conversion import fake_pdf
from signaling.test_report_finalization import photo_upload
from signaling import test_reservation_concurrency as core
from signaling.surveys import ANALYSIS_SESSION_KEY


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL and isolated test database")
class ReportFinalizationPostgreSQLTests(TransactionTestCase):
    reservation_permissions = ("view_signalingpoint", "generate_signaling_report", "finalize_technicalreport")
    acquire = core.PostgreSQLReservationConcurrencyTests.acquire
    release = core.PostgreSQLReservationConcurrencyTests.release
    submit = core.PostgreSQLReservationConcurrencyTests.submit
    race = core.PostgreSQLReservationConcurrencyTests.race
    lock_point = core.PostgreSQLReservationConcurrencyTests.lock_point
    wait_for_lock = core.PostgreSQLReservationConcurrencyTests.wait_for_lock

    def setUp(self):
        core.PostgreSQLReservationConcurrencyTests.setUp(self)
        self.user_id = self.client.session["_auth_user_id"]
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(REPORT_FINALIZATION_ENABLED=True, REPORT_PRIVATE_ROOT=self.temp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.renderer = patch.object(service, "render_snapshot", return_value=b"synthetic-docx")
        self.renderer.start()
        self.addCleanup(self.renderer.stop)
        self.converter = patch.object(service, "convert_docx_to_pdf", return_value=fake_pdf())
        self.convert = self.converter.start()
        self.addCleanup(self.converter.stop)
        self.draft = WaypointReportDraft.objects.create(signaling_point=self.point,
            inspection_address="Synthetic avenue", inspection_date="2026-10-28", inspector_name="Inspector",
            technical_analysis="Frozen conclusion", pgts=["School"], revision=1)
        self.set_analysis()
        self.grant = self.acquire()
        self.key = uuid4()

    def set_analysis(self):
        session = self.client.session
        session[ANALYSIS_SESSION_KEY] = {"view_mode": "individual", "analysis_id": "synthetic", "map_data": []}
        session.save()

    def client_for_thread(self):
        client = Client()
        client.cookies[settings.SESSION_COOKIE_NAME] = self.identity.session_key
        return client

    def headers(self, grant=None):
        proof = (grant or self.grant).credentials
        return {"HTTP_X_WAYPOINT_TOKEN": proof.token,
                "HTTP_X_WAYPOINT_INTERACTION": str(proof.interaction_id),
                "HTTP_X_WAYPOINT_GENERATION": str(proof.generation)}

    def post(self, key=None, point=None, grant=None, **changes):
        data = {"idempotency_key": str(key or self.key), "expected_revision": 1} | changes
        return self.client_for_thread().post(reverse("signaling:finalize-report", args=[(point or self.point).pk]),
            data, content_type="application/json", **self.headers(grant))

    def retry_http(self, attempt, grant=None):
        return self.client_for_thread().post(reverse("signaling:retry-report-finalization", args=[attempt.pk]),
            {}, content_type="application/json", **self.headers(grant))

    def expire(self):
        now = r._database_now()
        WaypointReservation.objects.filter(signaling_point=self.point).update(
            acquired_at=now-timedelta(seconds=3), renewed_at=now-timedelta(seconds=2), expires_at=now-timedelta(seconds=1))

    def test_success_snapshot_files_hashes_and_no_transaction_during_conversion(self):
        def convert(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            return fake_pdf()
        self.convert.side_effect = convert
        response = self.post()
        self.assertEqual(response.status_code, 201)
        attempt = Attempt.objects.select_related("version__report").get()
        self.assertEqual(attempt.state, "FINALIZED")
        self.assertEqual(attempt.version.snapshot_sha256, digest(attempt.version.snapshot))
        self.assertEqual(attempt.version.snapshot["form"]["technical_analysis"], "Frozen conclusion")
        self.assertEqual(attempt.version.author_id, int(self.user_id))
        self.assertIsNotNone(attempt.version.report.number_assigned_at)
        self.assertEqual(ReportArtifact.objects.count(), 2)
        storage = PrivateReportStorage()
        for artifact in ReportArtifact.objects.all():
            self.assertTrue(storage.read(artifact))
        self.assertNotIn("storage_key", response.content.decode())
        self.assertNotIn("token", str(attempt.version.snapshot))

    def test_same_idempotency_key_replays_without_conversion_or_active_reservation(self):
        first = self.post()
        self.release(self.grant)
        second = self.post()
        self.assertEqual(first.json()["report_id"], second.json()["report_id"])
        self.assertEqual(self.convert.call_count, 1)
        self.assertEqual(TechnicalReport.objects.count(), 1)
        self.assertEqual(self.post(expected_revision=2).status_code, 409)

    def test_annual_number_and_sao_paulo_new_year_consistency(self):
        with patch.object(service, "official_issued_at", return_value=datetime(2027, 1, 1, 1, 30, tzinfo=dt_timezone.utc).astimezone(service.OFFICIAL_TIMEZONE)):
            self.assertEqual(self.post().json()["number"], "RTSV-2026-0001")
        with patch.object(service, "official_issued_at", return_value=datetime(2027, 1, 1, 3, 30, tzinfo=dt_timezone.utc).astimezone(service.OFFICIAL_TIMEZONE)):
            self.assertEqual(self.post(key=uuid4()).json()["number"], "RTSV-2027-0001")
        versions = list(TechnicalReportVersion.objects.order_by("report__year"))
        self.assertEqual(versions[0].snapshot["issued_at"], "2026-12-31T22:30:00-03:00")
        self.assertEqual(versions[1].snapshot["issued_at"], "2027-01-01T00:30:00-03:00")

    def test_simultaneous_same_key_creates_only_one_report_and_conversion(self):
        results = self.race(self.post, self.post)
        self.assertTrue(all(result.status_code in (200, 201, 202) for result in results))
        self.assertEqual(TechnicalReport.objects.count(), 1)
        self.assertEqual(Attempt.objects.count(), 1)
        self.assertEqual(self.convert.call_count, 1)

    def test_simultaneous_different_points_serialize_first_annual_counter(self):
        point = SignalingPoint.objects.create(latitude=1, longitude=1, status="OK")
        WaypointReportDraft.objects.create(signaling_point=point, inspection_address="Other", inspection_date="2026-10-28", inspector_name="Other")
        grant = r.acquire_reservation(point_id=point.pk, identity=self.identity, interaction_id=uuid4())
        results = self.race(self.post, lambda: self.post(key=uuid4(), point=point, grant=grant))
        self.assertEqual([result.status_code for result in results], [201, 201])
        self.assertEqual(sorted(TechnicalReport.objects.values_list("sequence", flat=True)), [1, 2])
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 2)

    def test_conversion_timeout_failure_keeps_number_and_snapshot_and_explicit_retry(self):
        self.convert.side_effect = PDFConversionError("conversion_timeout")
        response = self.post()
        self.assertEqual(response.status_code, 503)
        attempt = Attempt.objects.select_related("version__report").get()
        frozen_hash = attempt.version.snapshot_sha256
        self.assertEqual(attempt.state, "FAILED")
        self.assertIsNone(attempt.version.report.number_assigned_at)
        self.assertEqual(self.post().status_code, 409)
        self.convert.side_effect = None
        self.assertEqual(self.retry_http(attempt).status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "FINALIZED")
        self.assertEqual(attempt.version.snapshot_sha256, frozen_hash)
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)

    def test_failed_conversion_leaves_gap_for_next_intention(self):
        self.convert.side_effect = PDFConversionError("conversion_failed")
        self.assertEqual(self.post().status_code, 503)
        self.convert.side_effect = None
        self.assertTrue(self.post(key=uuid4()).json()["number"].endswith("0002"))

    def test_storage_failure_is_not_published(self):
        with patch.object(PrivateReportStorage, "save", side_effect=ArtifactStorageError("artifact_storage_failed")):
            self.assertEqual(self.post().status_code, 503)
        self.assertEqual(Attempt.objects.get().state, "FAILED")
        self.assertIsNone(TechnicalReport.objects.get().number_assigned_at)
        self.assertIsNone(TechnicalReportVersion.objects.get().finalized_at)

    def test_expiration_during_conversion_is_recoverable_without_publication(self):
        started, finish = Event(), Event()

        def convert(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            started.set()
            if not finish.wait(timeout=10):
                raise AssertionError("Test did not release the delayed converter")
            return fake_pdf()

        self.convert.side_effect = convert
        pending, _ = self.submit(self.post)
        try:
            self.assertTrue(started.wait(timeout=8))
            # A different PostgreSQL connection can lock the waypoint WHILE conversion
            # is paused. Force expiration without waiting the full reservation TTL.
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '2s'")
                self.lock_point()
                self.expire()
        finally:
            finish.set()
        response = pending.result(timeout=12)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "reservation_expired")
        attempt = Attempt.objects.get()
        self.assertEqual(attempt.state, "FAILED")
        self.assertIsNone(attempt.version.finalized_at)
        self.convert.side_effect = None
        new_grant = self.acquire()
        self.assertEqual(self.retry_http(attempt, new_grant).status_code, 200)
        self.assertEqual(TechnicalReport.objects.count(), 1)

    def test_permission_revoked_during_conversion_prevents_publication(self):
        def convert(*args, **kwargs):
            from django.contrib.auth import get_user_model
            get_user_model().objects.get(pk=self.user_id).user_permissions.remove(Permission.objects.get(codename="finalize_technicalreport"))
            return fake_pdf()
        self.convert.side_effect = convert
        self.assertEqual(self.post().status_code, 403)
        self.assertIsNone(TechnicalReportVersion.objects.get().finalized_at)

    def test_source_changed_during_conversion_prevents_publication(self):
        def convert(*args, **kwargs):
            SignalingIntervention.objects.create(signaling_point=self.point, type="R1", condition="OK", notes="New note")
            return fake_pdf()
        self.convert.side_effect = convert
        self.assertEqual(self.post().json()["code"], "report_source_changed")
        self.assertIsNone(TechnicalReportVersion.objects.get().finalized_at)

    def test_finalized_survives_waypoint_and_draft_deletion_without_mutation(self):
        self.assertEqual(self.post().status_code, 201)
        version = TechnicalReportVersion.objects.get()
        before = version.snapshot
        self.draft.technical_analysis = "Later draft"
        self.draft.save()
        self.point.delete()
        version.refresh_from_db()
        self.assertEqual(version.snapshot, before)
        self.assertIsNone(version.report.waypoint_id)
        self.assertTrue(PrivateReportStorage().read(version.artifacts.get(kind="DOCX")))
        self.assertEqual(version.report.waypoint_history["id"], self.point.pk or before["source"]["point"]["id"])
        # Actual rendering is independent of the deleted live data.
        self.assertTrue(render_snapshot(version.snapshot, []).startswith(b"PK"))

    def test_photos_are_original_ordered_and_kept_for_retry(self):
        client = self.client_for_thread()
        self.convert.side_effect = PDFConversionError("conversion_failed")
        response = client.post(reverse("signaling:finalize-report", args=[self.point.pk]),
            {"idempotency_key": str(self.key), "expected_revision": "1", "photos": [photo_upload(), photo_upload()]}, **self.headers())
        self.assertEqual(response.status_code, 503)
        attempt = Attempt.objects.get()
        photos = list(attempt.version.artifacts.filter(kind="PHOTO").order_by("ordinal"))
        self.assertEqual([p.ordinal for p in photos], [0, 1])
        original_keys = [p.storage_key for p in photos]
        self.convert.side_effect = None
        self.assertEqual(self.retry_http(attempt).status_code, 200)
        self.assertEqual(list(attempt.version.artifacts.filter(kind="PHOTO").order_by("ordinal").values_list("storage_key", flat=True)), original_keys)

    def test_interrupted_execution_is_reclaimed_once_and_old_worker_is_fenced(self):
        self.convert.side_effect = PDFConversionError("conversion_failed")
        self.post()
        attempt = Attempt.objects.get()
        old_execution = attempt.execution_id
        Attempt.objects.filter(pk=attempt.pk).update(state="PROCESSING", deadline=timezone.now()-timedelta(seconds=1))
        call_command("reconcile_report_finalizations", stdout=StringIO())
        self.assertEqual(Attempt.objects.get().state, "PROCESSING")
        call_command("reconcile_report_finalizations", mark_interrupted=True, stdout=StringIO())
        self.assertEqual(Attempt.objects.get().state, "INTERRUPTED")
        self.convert.side_effect = None
        results = self.race(lambda: self.retry_http(attempt), lambda: self.retry_http(attempt))
        self.assertTrue(all(result.status_code in (200, 202) for result in results))
        self.assertEqual(self.convert.call_count, 2)
        with transaction.atomic():
            with self.assertRaises(service.FinalizationError):
                service._assert_run(attempt.pk, old_execution)

    def test_invalid_revision_payload_and_author_number_injection_rejected(self):
        self.assertEqual(self.post(expected_revision=0).status_code, 409)
        self.assertEqual(self.post(author="forged").status_code, 400)
        self.assertEqual(self.post(official_number="RTSV-2026-9999").status_code, 400)
        self.assertFalse(TechnicalReport.objects.exists())

    def test_csrf_authentication_permission_and_attempt_ownership(self):
        url = reverse("signaling:finalize-report", args=[self.point.pk])
        self.assertEqual(Client().post(url, {}, content_type="application/json").status_code, 401)
        csrf = Client(enforce_csrf_checks=True)
        csrf.cookies[settings.SESSION_COOKIE_NAME] = self.identity.session_key
        self.assertEqual(csrf.post(url, {}, content_type="application/json", **self.headers()).status_code, 403)
        self.assertEqual(self.post().status_code, 201)
        from signaling.test_support import authorize
        other = Client()
        authorize(other, self.reservation_permissions)
        self.assertEqual(other.get(reverse("signaling:report-finalization-status", args=[Attempt.objects.get().pk])).status_code, 404)
        from django.contrib.auth import get_user_model
        get_user_model().objects.get(pk=self.user_id).user_permissions.remove(Permission.objects.get(codename="finalize_technicalreport"))
        self.assertEqual(self.post(key=uuid4()).status_code, 403)

    def test_expiration_while_waiting_for_waypoint_lock_rejects_before_number(self):
        with transaction.atomic():
            self.lock_point()
            pending, pid = self.submit(self.post)
            self.wait_for_lock(pid, pending)
            self.expire()
        self.assertEqual(pending.result(timeout=12).status_code, 409)
        self.assertFalse(TechnicalReport.objects.exists())

    def test_snapshot_captures_only_used_accidents_and_historical_items(self):
        from signaling.services import create_point_problem
        SignalingIntervention.objects.create(signaling_point=self.point, type="R1", condition="OK", notes="Historical note")
        create_point_problem(self.point, "P1", ["P1A"])
        accident = {"id": "SYNTHETIC-1", "latitude": 0, "longitude": 0, "category": "collision",
                    "year": 2026, "month": 10, "record_type": "SINISTRO NAO FATAL", "date": "28/10/2026"}
        session = self.client.session
        session[ANALYSIS_SESSION_KEY]["map_data"] = [accident, accident | {"id": "OUTSIDE", "latitude": 10}]
        session.save()
        self.assertEqual(self.post().status_code, 201)
        snapshot = TechnicalReportVersion.objects.get().snapshot
        self.assertEqual([item["id"] for item in snapshot["survey"]["accidents"]], ["SYNTHETIC-1"])
        self.assertEqual(snapshot["source"]["items"]["interventions"][0]["notes"], "Historical note")
        self.assertTrue(snapshot["source"]["items"]["problems"][0]["solutions"][0]["text"])
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertIn("gravity", snapshot["filters"])

    def test_historical_inputs_cannot_be_overwritten_and_new_version_is_independent(self):
        from django.core.exceptions import ValidationError
        self.assertEqual(self.post().status_code, 201)
        version = TechnicalReportVersion.objects.get()
        original = version.snapshot_sha256
        with self.assertRaises(ValidationError):
            TechnicalReportVersion.objects.filter(pk=version.pk).update(snapshot={})
        version.snapshot = {}
        with self.assertRaises(ValidationError):
            version.save()
        version.refresh_from_db()
        new_snapshot = dict(version.snapshot) | {"form": dict(version.snapshot["form"]) | {"technical_analysis": "Later version"}}
        TechnicalReportVersion.objects.create(report=version.report, version=2, snapshot=new_snapshot,
            snapshot_sha256=digest(new_snapshot), source_sha256=version.source_sha256,
            author_id=version.author_id, author_identity=version.author_identity, issued_at=version.issued_at)
        version.refresh_from_db()
        self.assertEqual(version.snapshot_sha256, original)
        self.assertEqual(version.snapshot["form"]["technical_analysis"], "Frozen conclusion")

    def test_public_registration_does_not_receive_finalization_permission(self):
        from accounts.services import register_analyst
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from types import SimpleNamespace
        group, _ = Group.objects.get_or_create(name="analista")
        group.permissions.add(Permission.objects.get(codename="view_signalingpoint"))
        user = get_user_model()(username="new-public-user")
        user.set_unusable_password()
        created = register_analyst(SimpleNamespace(save=lambda commit: user))
        self.assertFalse(created.has_perm(service.FINALIZE))
        self.assertFalse(group.permissions.filter(codename="finalize_technicalreport").exists())

    def test_invalid_pdf_is_never_published(self):
        self.convert.return_value = b"not a PDF"
        self.assertEqual(self.post().status_code, 503)
        self.assertIsNone(TechnicalReportVersion.objects.get().finalized_at)
        self.assertEqual(Attempt.objects.get().error_code, "invalid_pdf")

    def test_lost_response_replay_does_not_require_original_session_analysis(self):
        response = self.post()
        session = self.client.session
        session.pop(ANALYSIS_SESSION_KEY, None)
        session.save()
        self.assertEqual(self.post().json()["report_id"], response.json()["report_id"])
        self.assertEqual(self.convert.call_count, 1)

    def test_read_only_reconciliation_never_deletes_finalized_files(self):
        self.assertEqual(self.post().status_code, 201)
        storage = PrivateReportStorage()
        before = list(storage.keys())
        call_command("reconcile_report_finalizations", delete_orphans=True, stdout=StringIO())
        self.assertEqual(list(storage.keys()), before)

    def test_stale_generation_and_inactive_reservation_cannot_finalize(self):
        self.release(self.grant)
        self.assertEqual(self.post().status_code, 409)
        self.acquire()
        self.assertEqual(self.post().json()["code"], "reservation_generation_stale")
        self.assertFalse(TechnicalReport.objects.exists())

    def post_original_photo(self, *, retry_attempt=None):
        url = (reverse("signaling:retry-report-finalization", args=[retry_attempt.pk]) if retry_attempt
               else reverse("signaling:finalize-report", args=[self.point.pk]))
        payload = {"photos": [photo_upload()]}
        if not retry_attempt:
            payload.update(idempotency_key=str(self.key), expected_revision="1")
        return self.client_for_thread().post(url, payload, **self.headers())

    def assert_photo_retry_identity(self, attempt, snapshot_hash, number):
        self.assertEqual(self.post_original_photo(retry_attempt=attempt).status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "FINALIZED")
        self.assertEqual(attempt.idempotency_key, self.key)
        self.assertEqual(attempt.version.snapshot_sha256, snapshot_hash)
        self.assertEqual(attempt.version.report.official_number, number)
        self.assertEqual(TechnicalReport.objects.count(), 1)
        self.assertEqual(Attempt.objects.count(), 1)
        self.assertEqual(attempt.version.artifacts.count(), 3)

    def test_photo_verification_failure_preserves_file_and_retry_with_original_succeeds(self):
        with patch.object(PrivateReportStorage, "read", side_effect=ArtifactStorageError("artifact_missing")):
            self.assertEqual(self.post_original_photo().status_code, 503)
        attempt = Attempt.objects.select_related("version__report").get()
        self.assertEqual(attempt.state, "FAILED")
        self.assertFalse(attempt.version.artifacts.exists())
        self.assertEqual(len(list(PrivateReportStorage().keys())), 1)
        self.assert_photo_retry_identity(attempt, attempt.version.snapshot_sha256, attempt.version.report.official_number)

    def test_photo_registration_failure_preserves_file_and_retry_with_original_succeeds(self):
        from django.db import OperationalError
        with patch.object(ReportArtifact.objects, "create", side_effect=OperationalError("registration failed")):
            self.assertEqual(self.post_original_photo().status_code, 503)
        attempt = Attempt.objects.select_related("version__report").get()
        self.assertFalse(attempt.version.artifacts.exists())
        self.assertEqual(len(list(PrivateReportStorage().keys())), 1)
        self.assert_photo_retry_identity(attempt, attempt.version.snapshot_sha256, attempt.version.report.official_number)

    def test_acknowledgement_failure_after_real_commit_preserves_photo_for_retry(self):
        from django.db import OperationalError
        original_store = service._store
        def store(*args, **kwargs):
            artifact = original_store(*args, **kwargs)
            # Actual PostgreSQL transaction already committed the photo. Caller
            # cannot tell whether it committed when acknowledgement is lost.
            if artifact.kind == "PHOTO":
                raise OperationalError("commit acknowledgement lost")
            return artifact
        with patch.object(service, "_store", side_effect=store):
            self.assertEqual(self.post_original_photo().status_code, 503)
        attempt = Attempt.objects.select_related("version__report").get()
        photo = attempt.version.artifacts.get(kind="PHOTO")
        self.assertTrue(PrivateReportStorage().read(photo))
        old_key = photo.storage_key
        frozen_hash, number = attempt.version.snapshot_sha256, attempt.version.report.official_number
        self.assertEqual(self.retry_http(attempt).status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual(attempt.version.snapshot_sha256, frozen_hash)
        self.assertEqual(attempt.version.report.official_number, number)
        self.assertEqual(attempt.idempotency_key, self.key)
        self.assertEqual(attempt.version.artifacts.get(kind="PHOTO").storage_key, old_key)
        self.assertTrue(PrivateReportStorage().read(photo))
