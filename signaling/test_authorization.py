import json

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.db import transaction
from django.urls import reverse
from unittest.mock import patch

from signaling.models import SignalingIntervention, SignalingPoint, SignalingPointProblem
from signaling.surveys import ANALYSIS_SESSION_KEY
from signaling.test_support import authorize


class AuthorizationTests(TestCase):
    def setUp(self):
        self.point = SignalingPoint.objects.create(
            latitude="-21.170000", longitude="-47.810000", status="OK",
        )
        self.intervention = SignalingIntervention.objects.create(
            signaling_point=self.point, type="R1", condition="OK", notes="PROTECTED-NOTES",
        )
        self.problem = SignalingPointProblem.objects.create(
            signaling_point=self.point, problem_code="P1",
        )

    def operations(self):
        p, i, problem = self.point.pk, self.intervention.pk, self.problem.pk
        return [
            ("create-point", [], {"latitude": 0, "longitude": 0, "status": "OK"}, "add_signalingpoint"),
            ("delete-point", [p], {}, "delete_signalingpoint"),
            ("update-point-status", [p], {"status": "ABSENT"}, "change_signalingpoint"),
            ("update-point-search-radius", [p], {"search_radius_meters": 60}, "change_signalingpoint"),
            ("save-intervention", [p], {"type": "R1", "condition": "OK"}, "change_signalingpoint"),
            ("delete-intervention", [p, i], {}, "change_signalingpoint"),
            ("update-intervention-condition", [p, i], {"condition": "ABSENT"}, "change_signalingpoint"),
            ("update-intervention-notes", [p, i], {"notes": "changed"}, "change_signalingpoint"),
            ("point-problems", [p], {"problem_code": "P2", "solution_codes": ["P2A"]}, "change_signalingpoint"),
            ("update-problem-solution", [p, problem], {"solution_codes": ["P1A"]}, "change_signalingpoint"),
            ("delete-point-problem", [p, problem], {}, "change_signalingpoint"),
            ("search-point-pgts", [p], {}, "generate_signaling_report"),
        ]

    def post(self, client, name, args, data):
        return client.post(reverse("signaling:" + name, args=args),
                           json.dumps(data), content_type="application/json")

    def test_all_api_writes_reject_anonymous_and_insufficient_permissions_without_side_effects(self):
        counts = (SignalingPoint.objects.count(), SignalingIntervention.objects.count(),
                  SignalingPointProblem.objects.count())
        with patch("signaling.views.find_nearby_pgts") as search:
            for name, args, data, operation in self.operations():
                for permissions, status, code in [
                    (None, 401, "authentication_required"),
                    ((), 403, "permission_denied"),
                    (("view_signalingpoint",), 403, "permission_denied"),
                    ((operation,), 403, "permission_denied"),
                ]:
                    with self.subTest(endpoint=name, permissions=permissions):
                        client = Client()
                        if permissions is not None:
                            authorize(client, permissions)
                        response = self.post(client, name, args, data)
                        self.assertEqual(response.status_code, status)
                        self.assertEqual(response.json()["code"], code)
            search.assert_not_called()
        self.assertEqual(counts, (SignalingPoint.objects.count(), SignalingIntervention.objects.count(),
                                 SignalingPointProblem.objects.count()))
        self.point.refresh_from_db()
        self.intervention.refresh_from_db()
        self.assertEqual(self.point.status, "OK")
        self.assertEqual(self.point.search_radius_meters, 50)
        self.assertEqual(self.intervention.notes, "PROTECTED-NOTES")

    def test_each_api_accepts_only_its_minimum_operation_permissions(self):
        from signaling.test_support import ReservationClient
        from django.db import connection
        from contextlib import nullcontext
        guard = patch("signaling.reservations._require_locking_backend") if connection.vendor == "sqlite" else nullcontext()
        with guard, patch("signaling.views.find_nearby_pgts", return_value=[]):
            for name, args, data, operation in self.operations():
                with self.subTest(endpoint=name), transaction.atomic():
                    client = ReservationClient()
                    user = authorize(client, ("view_signalingpoint", operation))
                    self.assertFalse(user.is_staff)
                    self.assertFalse(user.is_superuser)
                    response = self.post(client, name, args, data)
                    self.assertIn(response.status_code, (200, 201), response.content)
                    transaction.set_rollback(True)

    def test_view_only_can_read_problems_but_not_report(self):
        authorize(self.client, ("view_signalingpoint",))
        self.assertEqual(self.client.get(reverse("signaling:point-problems",
                                                args=[self.point.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("signaling:point-report",
                                                args=[self.point.pk])).status_code, 403)

    def test_problem_read_requires_identity_and_view(self):
        url = reverse("signaling:point-problems", args=[self.point.pk])
        self.assertEqual(self.client.get(url).status_code, 401)
        authorize(self.client, ())
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_map_public_but_payload_is_authorized(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["signaling_map_data"], [])
        self.assertNotContains(response, "PROTECTED-NOTES")
        authorize(self.client, ())
        self.assertEqual(self.client.get("/").context["signaling_map_data"], [])
        self.client.logout()
        authorize(self.client, ("view_signalingpoint",))
        response = self.client.get("/")
        self.assertEqual(len(response.context["signaling_map_data"]), 1)
        self.assertContains(response, "PROTECTED-NOTES")
        self.assertContains(response, 'data-can-change="false"')
        self.assertContains(response, 'data-can-report="false"')

    def test_report_redirect_and_permission_checks_precede_object_lookup(self):
        url = reverse("signaling:point-report", args=[999999])
        for method in ("get", "post"):
            response = getattr(self.client, method)(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("login") + "?next="))
        authorize(self.client, ("generate_signaling_report",))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        authorize(self.client, ("view_signalingpoint", "generate_signaling_report"))
        self.assertEqual(self.client.get(url).status_code, 428)

    def test_authenticated_api_csrf_is_still_required(self):
        client = Client(enforce_csrf_checks=True)
        authorize(client, ("view_signalingpoint", "change_signalingpoint"))
        url = reverse("signaling:update-point-status", args=[self.point.pk])
        failure = client.post(url, '{"status":"ABSENT"}', content_type="application/json")
        self.assertEqual(failure.status_code, 403)
        self.assertEqual(failure.json()["code"], "csrf_failed")
        client.get("/")
        response = client.post(url, '{"status":"ABSENT"}', content_type="application/json",
                               HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 428)
        self.assertEqual(response.json()["code"], "reservation_required")

    def test_expired_session_gets_json_401(self):
        authorize(self.client, ("view_signalingpoint",))
        self.client.session.flush()
        response = self.client.get(reverse("signaling:point-problems", args=[self.point.pk]))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "authentication_required")


class LoginTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="login-test", password="A-test-password-9384",
        )

    def test_login_preserves_anonymous_analysis_and_rejects_external_next(self):
        session = self.client.session
        session[ANALYSIS_SESSION_KEY] = {"view_mode": "individual", "map_data": []}
        session.save()
        response = self.client.post(reverse("login"), {
            "username": self.user.username, "password": "A-test-password-9384",
            "next": "https://outside.example/steal",
        })
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertIn(ANALYSIS_SESSION_KEY, self.client.session)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.user_permissions.exists())

    def test_login_error_safe_next_and_inactive_user(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        response = self.client.post(reverse("login"), {"username": self.user.username,
                                                       "password": "incorrect"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post(reverse("login"), {
            "username": self.user.username, "password": "A-test-password-9384",
            "next": "/?clear=1",
        })
        self.assertRedirects(response, "/?clear=1", fetch_redirect_response=False)
        self.client.logout()
        self.user.is_active = False
        self.user.save()
        self.client.post(reverse("login"), {"username": self.user.username,
                                            "password": "A-test-password-9384"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_post_csrf_and_session_clear(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        session = client.session
        session[ANALYSIS_SESSION_KEY] = {"map_data": []}
        session.save()
        self.assertEqual(client.get(reverse("logout")).status_code, 405)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)
        response = client.get("/")
        self.assertContains(response, "Sair e encerrar análise")
        response = client.post(reverse("logout"),
                               HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertNotIn(ANALYSIS_SESSION_KEY, client.session)
        self.assertNotIn("_auth_user_id", client.session)


class AdminAuthorizationTests(TestCase):
    def setUp(self):
        self.point = SignalingPoint.objects.create(latitude=0, longitude=0, status="OK")
        self.intervention = SignalingIntervention.objects.create(
            signaling_point=self.point, type="R1", condition="OK",
        )

    def staff(self, *codenames):
        user = authorize(self.client, codenames)
        user.is_staff = True
        user.save()
        return user

    def test_native_child_permissions_do_not_bypass_waypoint_policy(self):
        self.staff("view_signalingintervention", "add_signalingintervention",
                   "change_signalingintervention", "delete_signalingintervention")
        for name, args in [
            ("admin:signaling_signalingintervention_changelist", []),
            ("admin:signaling_signalingintervention_add", []),
            ("admin:signaling_signalingintervention_change", [self.intervention.pk]),
            ("admin:signaling_signalingintervention_delete", [self.intervention.pk]),
        ]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
        response = self.client.post(reverse("admin:signaling_signalingintervention_changelist"), {
            "action": "delete_selected", "_selected_action": [self.intervention.pk], "post": "yes",
        })
        self.assertEqual(response.status_code, 403)
        self.assertTrue(SignalingIntervention.objects.filter(pk=self.intervention.pk).exists())

    def test_aggregate_permissions_do_not_replace_native_child_permissions(self):
        self.staff("view_signalingpoint", "change_signalingpoint")
        self.assertEqual(self.client.get(reverse(
            "admin:signaling_signalingintervention_change", args=[self.intervention.pk],
        )).status_code, 403)

    def test_waypoint_change_without_view_cannot_open_admin_details(self):
        self.staff("change_signalingpoint")
        self.assertEqual(self.client.get(reverse(
            "admin:signaling_signalingpoint_change", args=[self.point.pk],
        )).status_code, 403)

    def test_waypoint_bulk_delete_cannot_bypass_missing_view(self):
        self.staff("delete_signalingpoint", "delete_signalingintervention")
        response = self.client.post(reverse("admin:signaling_signalingpoint_changelist"), {
            "action": "delete_selected", "_selected_action": [self.point.pk], "post": "yes",
        })
        self.assertEqual(response.status_code, 403)
        self.assertTrue(SignalingPoint.objects.filter(pk=self.point.pk).exists())

    def test_admin_requires_both_layers_for_each_child_operation(self):
        user = self.staff("view_signalingpoint", "change_signalingpoint",
                          "view_signalingintervention", "add_signalingintervention",
                          "change_signalingintervention", "delete_signalingintervention")
        model_admin = site._registry[SignalingIntervention]
        from django.test import RequestFactory
        request = RequestFactory().get("/")
        request.user = user
        self.assertTrue(model_admin.has_view_permission(request, self.intervention))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, self.intervention))
        self.assertFalse(model_admin.has_delete_permission(request, self.intervention))


class WaypointCreationSecurityTests(TestCase):
    payload = {"latitude": -21.17, "longitude": -47.81, "status": "OK"}

    def csrf(self, client):
        client.get("/")
        return client.cookies["csrftoken"].value

    def create(self, client, token=None, **headers):
        if token is not None:
            headers["HTTP_X_CSRFTOKEN"] = token
        return client.post(reverse("signaling:create-point"),
                           json.dumps(self.payload), content_type="application/json", **headers)

    def test_creation_permission_matrix_with_real_csrf(self):
        for permissions, status, code in [
            (None, 401, "authentication_required"),
            ((), 403, "permission_denied"),
            (("view_signalingpoint",), 403, "permission_denied"),
            (("add_signalingpoint",), 403, "permission_denied"),
            (("view_signalingpoint", "add_signalingpoint"), 201, None),
        ]:
            with self.subTest(permissions=permissions):
                client = Client(enforce_csrf_checks=True)
                if permissions is not None:
                    user = authorize(client, permissions)
                    self.assertFalse(user.is_staff)
                    self.assertFalse(user.is_superuser)
                before = SignalingPoint.objects.count()
                response = self.create(client, self.csrf(client))
                self.assertEqual(response.status_code, status)
                self.assertEqual(response["Content-Type"], "application/json")
                if code:
                    self.assertEqual(response.json()["code"], code)
                    self.assertEqual(SignalingPoint.objects.count(), before)
                else:
                    self.assertTrue(SignalingPoint.objects.filter(pk=response.json()["id"]).exists())
                    self.assertEqual(SignalingPoint.objects.count(), before + 1)

    def test_missing_invalid_cookie_and_untrusted_origin_remain_forbidden(self):
        client = Client(enforce_csrf_checks=True)
        authorize(client, ("view_signalingpoint", "add_signalingpoint"))
        token = self.csrf(client)
        for bad_token in [None, "invalid", "a" * 32]:
            with self.subTest(token_present=bad_token is not None):
                response = self.create(client, bad_token)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["code"], "csrf_failed")
        response = self.create(client, token, HTTP_ORIGIN="https://untrusted.example")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")
        del client.cookies["csrftoken"]
        self.assertEqual(self.create(client, token).json()["code"], "csrf_failed")
        self.assertFalse(SignalingPoint.objects.exists())

    def test_old_dom_token_after_login_is_rejected_but_current_cookie_succeeds(self):
        client = Client(enforce_csrf_checks=True)
        user = authorize(client, ("view_signalingpoint", "add_signalingpoint"))
        user.set_password("Only-for-test-login-5813")
        user.save()
        client.force_login(user)
        response = client.get("/")
        import re
        old_dom_token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',
                                  response.content.decode()).group(1)
        old_cookie = client.cookies["csrftoken"].value
        response = client.post(reverse("login"), {
            "username": user.get_username(), "password": "Only-for-test-login-5813",
        }, HTTP_X_CSRFTOKEN=old_dom_token)
        self.assertEqual(response.status_code, 302)
        current_cookie = client.cookies["csrftoken"].value
        self.assertNotEqual(current_cookie, old_cookie)
        response = self.create(client, old_dom_token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")
        self.assertEqual(self.create(client, current_cookie).status_code, 201)

    def test_creation_never_enters_reservation_services_on_sqlite(self):
        client = Client(enforce_csrf_checks=True)
        authorize(client, ("view_signalingpoint", "add_signalingpoint"))
        token = self.csrf(client)
        with patch("signaling.reservations._require_locking_backend",
                   side_effect=AssertionError("Reservation locking must not be invoked")) as locking:
            with patch("signaling.reservations._authenticated_user",
                       side_effect=AssertionError("Reservation identity must not be invoked")) as identity:
                self.assertEqual(self.create(client, token).status_code, 201)
            identity.assert_not_called()
        locking.assert_not_called()

    def test_expired_session_with_valid_csrf_requires_login_without_writing(self):
        client = Client(enforce_csrf_checks=True)
        authorize(client, ("view_signalingpoint", "add_signalingpoint"))
        token = self.csrf(client)
        client.session.flush()
        response = self.create(client, token)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "authentication_required")
        self.assertFalse(SignalingPoint.objects.exists())
