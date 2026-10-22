from unittest import skipUnless
from uuid import uuid4

from django.db import connection, transaction
from django.conf import settings
from django.test import Client, TransactionTestCase
from django.urls import reverse

from signaling import reservations as r
from signaling import test_reservation_concurrency as core


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL")
class ReservationHTTPConcurrencyTests(TransactionTestCase):
    # The domain fixture needs view only; these HTTP operations also require
    # change/report. Grant them at fixture creation without changing the session.
    reservation_permissions = (
        "view_signalingpoint", "change_signalingpoint", "generate_signaling_report",
    )

    # Share only synchronization helpers; do not rediscover the domain tests here.
    setUp = core.PostgreSQLReservationConcurrencyTests.setUp
    acquire = core.PostgreSQLReservationConcurrencyTests.acquire
    release = core.PostgreSQLReservationConcurrencyTests.release
    submit = core.PostgreSQLReservationConcurrencyTests.submit
    race = core.PostgreSQLReservationConcurrencyTests.race
    wait_for_lock = core.PostgreSQLReservationConcurrencyTests.wait_for_lock
    lock_point = core.PostgreSQLReservationConcurrencyTests.lock_point
    assert_current = core.PostgreSQLReservationConcurrencyTests.assert_current

    def http_client(self):
        client = Client()
        client.cookies[settings.SESSION_COOKIE_NAME] = self.identity.session_key
        return client

    def acquire_http(self):
        return self.http_client().post(reverse("signaling:acquire-reservation",
            args=[self.point.pk]), {"interaction_id":str(uuid4())},
            content_type="application/json")

    def test_same_session_two_http_acquisitions_have_one_winner(self):
        results = self.race(self.acquire_http, self.acquire_http)
        self.assertEqual(sorted(result.status_code for result in results), [201,409])

    def test_old_http_mutation_waits_and_cannot_cross_new_generation(self):
        old = self.acquire()
        def mutate():
            return self.http_client().post(reverse("signaling:update-point-status",
                args=[self.point.pk]), {"status":"ABSENT"}, content_type="application/json",
                HTTP_X_WAYPOINT_TOKEN=old.credentials.token,
                HTTP_X_WAYPOINT_INTERACTION=str(old.credentials.interaction_id),
                HTTP_X_WAYPOINT_GENERATION=str(old.credentials.generation))
        with transaction.atomic():
            self.lock_point()
            pending, pid = self.submit(mutate)
            self.wait_for_lock(pid, pending)
            self.release(old)
            new = self.acquire()
        response = pending.result(timeout=12)
        self.assertEqual(response.status_code, 409,
            f"Unexpected HTTP {response.status_code}; content_type={response.get('Content-Type')}")
        self.assertEqual(response.json()["code"], "reservation_generation_stale")
        self.point.refresh_from_db()
        self.assertEqual(self.point.status, "OK")
        self.assert_current(new)


    def test_report_work_is_outside_transaction_with_real_postgresql(self):
        from unittest.mock import patch
        grant = self.acquire()
        client = self.http_client()
        session = client.session
        session["accident_analysis_state"] = {"view_mode":"individual", "map_data":[]}
        session.save()

        def graph(survey):
            self.assertFalse(connection.in_atomic_block)
            self.release(grant)
            self.acquire()
            return None

        with patch("signaling.views.build_accident_types_chart_data_uri", side_effect=graph) as processing:
            response = client.get(reverse("signaling:point-report", args=[self.point.pk]),
                HTTP_X_WAYPOINT_TOKEN=grant.credentials.token,
                HTTP_X_WAYPOINT_INTERACTION=str(grant.credentials.interaction_id),
                HTTP_X_WAYPOINT_GENERATION=str(grant.credentials.generation))
        self.assertEqual(response.status_code, 409,
            f"Unexpected HTTP {response.status_code}; content_type={response.get('Content-Type')}")
        self.assertEqual(response.json()["code"], "reservation_generation_stale")
        processing.assert_called_once()


    def test_view_only_fixture_is_denied_before_reservation_validation(self):
        from unittest.mock import patch
        from signaling.test_support import authorize

        grant = self.acquire()
        reader = Client()
        user = authorize(reader, ("view_signalingpoint",))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        headers = {
            "HTTP_X_WAYPOINT_TOKEN": grant.credentials.token,
            "HTTP_X_WAYPOINT_INTERACTION": str(grant.credentials.interaction_id),
            "HTTP_X_WAYPOINT_GENERATION": str(grant.credentials.generation),
        }
        with patch("signaling.reservation_http.domain.validate_reservation") as validation:
            response = reader.post(reverse("signaling:update-point-status",
                args=[self.point.pk]), {"status": "ABSENT"},
                content_type="application/json", **headers)
            self.assertEqual(response.status_code, 403)
            self.assertTrue(response.wsgi_request.user.is_authenticated)
            self.assertEqual(response.json()["code"], "permission_denied")

            response = reader.get(reverse("signaling:point-report",
                args=[self.point.pk]), **headers)
            self.assertEqual(response.status_code, 403)
            self.assertTrue(response.wsgi_request.user.is_authenticated)
            self.assertIn("text/html", response["Content-Type"])
            validation.assert_not_called()
