"""Real PostgreSQL row-lock tests; never run as SQLite locking simulations."""
from datetime import timedelta
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse

from signaling.models import WaypointReportDraft, WaypointReservation
from signaling import reservations as r
from signaling import test_reservation_concurrency as core


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL")
class ReportDraftConcurrencyTests(TransactionTestCase):
    reservation_permissions = ("view_signalingpoint", "generate_signaling_report")
    setUp = core.PostgreSQLReservationConcurrencyTests.setUp
    acquire = core.PostgreSQLReservationConcurrencyTests.acquire
    release = core.PostgreSQLReservationConcurrencyTests.release
    submit = core.PostgreSQLReservationConcurrencyTests.submit
    race = core.PostgreSQLReservationConcurrencyTests.race
    lock_point = core.PostgreSQLReservationConcurrencyTests.lock_point
    wait_for_lock = core.PostgreSQLReservationConcurrencyTests.wait_for_lock

    def save_http(self, grant, revision, text):
        client = Client()
        client.cookies[settings.SESSION_COOKIE_NAME] = self.identity.session_key
        return client.post(reverse("signaling:report-draft", args=[self.point.pk]),
            {"expected_revision": revision, "fields": {"study_reason": text, "technical_analysis": text}},
            content_type="application/json",
            HTTP_X_WAYPOINT_TOKEN=grant.credentials.token,
            HTTP_X_WAYPOINT_INTERACTION=str(grant.credentials.interaction_id),
            HTTP_X_WAYPOINT_GENERATION=str(grant.credentials.generation))

    def assert_one_winner(self, results, revision):
        self.assertEqual(sorted(response.status_code for response in results), [200, 409])
        conflict = next(response for response in results if response.status_code == 409)
        self.assertEqual(conflict.json()["code"], "draft_revision_conflict")
        self.assertEqual(conflict.json()["revision"], revision)
        winner = next(response for response in results if response.status_code == 200)
        draft = WaypointReportDraft.objects.get(signaling_point=self.point)
        self.assertEqual(draft.revision, revision)
        self.assertEqual(draft.study_reason, winner.json()["fields"]["study_reason"])
        self.assertEqual(draft.technical_analysis, winner.json()["fields"]["technical_analysis"])
        self.assertEqual(WaypointReportDraft.objects.count(), 1)

    def test_concurrent_first_saves_create_one_draft(self):
        grant = self.acquire()
        self.assert_one_winner(self.race(
            lambda: self.save_http(grant, 0, "Primeiro"),
            lambda: self.save_http(grant, 0, "Segundo")), 1)

    def test_concurrent_updates_with_same_revision_have_one_winner(self):
        grant = self.acquire()
        self.assertEqual(self.save_http(grant, 0, "Inicial").status_code, 200)
        self.assert_one_winner(self.race(
            lambda: self.save_http(grant, 1, "Primeiro"),
            lambda: self.save_http(grant, 1, "Segundo")), 2)

    def test_waiting_old_generation_cannot_cross_new_acquisition(self):
        old = self.acquire()
        self.assertEqual(self.save_http(old, 0, "Inicial").status_code, 200)
        with transaction.atomic():
            self.lock_point()
            pending, pid = self.submit(lambda: self.save_http(old, 1, "Obsoleto"))
            self.wait_for_lock(pid, pending)
            self.release(old)
            self.acquire()
        response = pending.result(timeout=12)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "reservation_generation_stale")
        draft = WaypointReportDraft.objects.get(signaling_point=self.point)
        self.assertEqual(draft.study_reason, "Inicial")
        self.assertEqual(draft.technical_analysis, "Inicial")
        self.assertEqual(draft.revision, 1)

    def test_reservation_expiration_is_checked_after_waiting_for_lock(self):
        grant = self.acquire()
        with transaction.atomic():
            self.lock_point()
            pending, pid = self.submit(lambda: self.save_http(grant, 0, "Tardio"))
            self.wait_for_lock(pid, pending)
            now = r._database_now()
            WaypointReservation.objects.filter(signaling_point=self.point).update(
                acquired_at=now-timedelta(seconds=3), renewed_at=now-timedelta(seconds=2),
                expires_at=now-timedelta(seconds=1),
            )
        response = pending.result(timeout=12)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "reservation_expired")
        self.assertFalse(WaypointReportDraft.objects.exists())

    def test_report_permission_revocation_while_waiting_prevents_write(self):
        grant = self.acquire()
        with transaction.atomic():
            self.lock_point()
            pending, pid = self.submit(lambda: self.save_http(grant, 0, "Tardio"))
            self.wait_for_lock(pid, pending)
            user = get_user_model().objects.get(pk=self.client.session["_auth_user_id"])
            user.user_permissions.remove(*user.user_permissions.filter(
                codename="generate_signaling_report"))
        response = pending.result(timeout=12)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "permission_denied")
        self.assertFalse(WaypointReportDraft.objects.exists())
