"""Public registration coverage alongside existing authentication tests."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse


@override_settings(REGISTRATION_ENABLED=True)
class RegistrationTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="analista")
        self.group.permissions.add(Permission.objects.get(
            content_type__app_label="signaling", codename="view_signalingpoint",
        ))
        self.data = {
            "username": "new-analyst", "email": " New.Analyst@Example.COM ",
            "password1": "Unique-traffic-passphrase-9384",
            "password2": "Unique-traffic-passphrase-9384",
        }
        self.url = reverse("register")

    def post(self, **changes):
        return self.client.post(self.url, {**self.data, **changes})

    def test_valid_registration_inherits_only_group_permissions_without_login(self):
        response = self.post(is_staff="true", is_superuser="true", is_active="false",
                             groups="999", user_permissions="999")
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        user = get_user_model().objects.get(username=self.data["username"])
        self.assertEqual(user.email, "new.analyst@example.com")
        self.assertTrue(user.check_password(self.data["password1"]))
        self.assertNotEqual(user.password, self.data["password1"])
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(list(user.groups.all()), [self.group])
        self.assertFalse(user.user_permissions.exists())
        self.assertEqual(user.get_all_permissions(), {"signaling.view_signalingpoint"})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(self.client.get(reverse("login")), "Conta criada com sucesso")

    def test_form_exposes_only_public_fields_and_login_links_to_it(self):
        response = self.client.get(self.url)
        self.assertEqual(set(response.context["form"].fields),
                         {"username", "email", "password1", "password2"})
        self.assertNotContains(response, 'name="is_staff"')
        self.assertContains(self.client.get(reverse("login")), self.url)

    def test_existing_accounts_groups_and_permissions_are_unchanged(self):
        User = get_user_model()
        admin = User.objects.create_superuser("administrator", "admin@example.com", "Admin-only-9384")
        staff = User.objects.create_user("staff", "staff@example.com", "Staff-only-9384", is_staff=True)
        staff.groups.add(self.group)
        admin.user_permissions.add(self.group.permissions.first())
        self.client.force_login(admin)
        before = list(User.objects.order_by("pk").values())
        memberships = list(staff.groups.values_list("pk", flat=True))
        permissions = list(admin.user_permissions.values_list("pk", flat=True))
        self.post()
        self.assertEqual(list(User.objects.filter(pk__in=[admin.pk, staff.pk]).order_by("pk").values()), before)
        self.assertEqual(list(staff.groups.values_list("pk", flat=True)), memberships)
        self.assertEqual(list(admin.user_permissions.values_list("pk", flat=True)), permissions)
        self.assertEqual(int(self.client.session["_auth_user_id"]), admin.pk)

    def test_duplicate_username_is_rejected(self):
        get_user_model().objects.create_user("new-analyst", "other@example.com")
        response = self.post()
        self.assertIn("username", response.context["form"].errors)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_duplicate_email_is_case_and_surrounding_space_insensitive(self):
        get_user_model().objects.create_user("existing", "  NEW.ANALYST@EXAMPLE.COM  ")
        response = self.post()
        self.assertIn("email", response.context["form"].errors)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_required_valid_email(self):
        for email in ("", "   ", "not-an-email"):
            with self.subTest(email=email):
                response = self.post(email=email)
                self.assertIn("email", response.context["form"].errors)
        self.assertFalse(get_user_model().objects.exists())

    def test_native_password_validators_and_confirmation(self):
        for password1, password2 in (("tiny", "tiny"), ("123456789", "123456789"),
                                     ("password", "password"), ("new-analyst", "new-analyst"),
                                     (self.data["password1"], "different")):
            with self.subTest(password1=password1):
                response = self.post(password1=password1, password2=password2)
                self.assertTrue(response.context["form"].errors)
        self.assertFalse(get_user_model().objects.exists())

    def test_missing_exact_group_fails_safely_without_partial_account(self):
        self.group.name = "Analista"
        self.group.save()
        with self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "Não foi possível criar sua conta", status_code=503)
        self.assertNotContains(response, "ImproperlyConfigured", status_code=503)
        self.assertNotContains(response, "analista", status_code=503)
        self.assertFalse(get_user_model().objects.exists())
        self.assertEqual(Group.objects.count(), 1)
        self.assertIn("not provisioned", logs.output[0])

    def test_membership_write_failure_rolls_back_account(self):
        manager_type = type(get_user_model()(pk=999).groups)
        with patch.object(manager_type, "add", side_effect=IntegrityError("internal secret")):
            with self.assertLogs("accounts.views", level="ERROR") as logs:
                response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(get_user_model().objects.exists())
        self.assertNotContains(response, "internal secret", status_code=503)
        self.assertNotIn("internal secret", " ".join(logs.output))

    def test_concurrent_username_database_error_is_controlled(self):
        with patch("accounts.views.register_analyst", side_effect=IntegrityError("private SQL")):
            with self.assertLogs("accounts.views", level="ERROR"):
                response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private SQL", status_code=503)

    def test_csrf_required_and_valid_token_works(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.url, self.data).status_code, 403)
        self.assertFalse(get_user_model().objects.exists())
        client.get(self.url)
        response = client.post(self.url, self.data, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 302)

    def test_safe_next_survives_registration_and_login(self):
        target = "/?view=individual"
        response = self.post(next=target)
        self.assertEqual(urlsplit(response.url).path, reverse("login"))
        self.assertEqual(parse_qs(urlsplit(response.url).query), {"next": [target]})
        response = self.client.post(response.url, {
            "username": self.data["username"], "password": self.data["password1"], "next": target,
        })
        self.assertRedirects(response, target, fetch_redirect_response=False)

    def test_unsafe_next_is_discarded(self):
        response = self.post(next="https://outside.example/steal")
        self.assertEqual(response.url, reverse("login"))
        response = self.client.get(self.url, {"next": "//outside.example/steal"})
        self.assertEqual(response.context["next"], "")

    @override_settings(REGISTRATION_ENABLED=False)
    def test_disabled_registration_never_creates_account(self):
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(self.url, self.data).status_code, 403)
        self.assertFalse(get_user_model().objects.exists())

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
    def test_debug_false_success_and_generic_failure(self):
        self.assertEqual(self.post().status_code, 302)
        self.group.delete()
        with self.assertLogs("accounts.views", level="ERROR"):
            response = self.post(username="another", email="another@example.com")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(get_user_model().objects.filter(username="another").exists())

    def test_login_and_waypoint_permissions_follow_group_without_reservation_bypass(self):
        self.post()
        self.assertTrue(self.client.login(username=self.data["username"], password=self.data["password1"]))
        self.assertEqual(self.client.get(reverse("signaling:point-problems", args=[999])).status_code, 404)
        self.assertEqual(self.client.post(reverse("signaling:create-point"),
                                         data='{"latitude":0,"longitude":0,"status":"OK"}',
                                         content_type="application/json").status_code, 403)
        self.group.permissions.add(*Permission.objects.filter(
            content_type__app_label="signaling", codename__in=["add_signalingpoint", "change_signalingpoint"],
        ))
        response = self.client.post(reverse("signaling:create-point"),
                                    data='{"latitude":0,"longitude":0,"status":"OK"}',
                                    content_type="application/json")
        self.assertEqual(response.status_code, 201)
        from signaling.models import SignalingPoint
        point = SignalingPoint.objects.get()
        response = self.client.post(reverse("signaling:update-point-status", args=[point.pk]),
                                    data='{"status":"ABSENT"}', content_type="application/json")
        self.assertEqual(response.status_code, 428)
        point.refresh_from_db()
        self.assertEqual(point.status, "OK")
