"""Draft HTTP contracts. SQLite fixtures do not validate real row locking."""
from datetime import timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from signaling import reservations as r
from signaling.models import SignalingPoint, WaypointReportDraft, WaypointReservation
from signaling.test_support import authorize


class ReportDraftTests(TestCase):
    def setUp(self):
        if connection.vendor == "sqlite":
            guard = patch("signaling.reservations._require_locking_backend")
            guard.start()
            self.addCleanup(guard.stop)
        self.user = authorize(self.client)
        self.point = SignalingPoint.objects.create(latitude=0, longitude=0, status="OK")
        self.url = reverse("signaling:report-draft", args=[self.point.pk])
        self.proof = self.acquire(self.client, self.point)

    def acquire(self, client, point):
        grant = r.acquire_reservation(
            point_id=point.pk, identity=r.ReservationIdentity(client.session.session_key),
            interaction_id=uuid4(),
        )
        return {
            "HTTP_X_WAYPOINT_TOKEN": grant.credentials.token,
            "HTTP_X_WAYPOINT_INTERACTION": str(grant.credentials.interaction_id),
            "HTTP_X_WAYPOINT_GENERATION": str(grant.credentials.generation),
        }

    def save(self, fields, revision=0, client=None, proof=None, url=None):
        return (client or self.client).post(
            url or self.url, {"expected_revision": revision, "fields": fields},
            content_type="application/json", **(self.proof if proof is None else proof),
        )

    def expire(self):
        now = r._database_now()
        WaypointReservation.objects.filter(signaling_point=self.point).update(
            acquired_at=now-timedelta(seconds=3), renewed_at=now-timedelta(seconds=2),
            expires_at=now-timedelta(seconds=1),
        )

    def test_get_absent_is_revision_zero_without_creating_a_record(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision"], 0)
        self.assertFalse(response.json()["exists"])
        self.assertEqual(response.json()["fields"]["pgts"], [])
        self.assertFalse(WaypointReportDraft.objects.exists())
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])

    def test_create_and_retrieve_typed_data_and_author(self):
        values = {
            "inspection_address": "Rua São João", "inspection_date": "2026-10-27",
            "occurrence_date": "2026-10-01", "study_reason": "Vistoria",
            "study_objective": "Segurança", "inspector_name": "Maria",
            "functional_classification": "Arterial", "geometric_configuration": "Cruzamento",
            "regulated_speed": "40 km/h", "pgts": [" Escola ", "", "Hospital"],
        }
        response = self.save(values)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["revision"], 1)
        self.assertEqual(body["updated_by"], self.user.pk)
        self.assertIsNotNone(body["created_at"])
        self.assertIsNotNone(body["updated_at"])
        self.assertEqual(body["fields"]["pgts"], ["Escola", "Hospital"])
        self.assertEqual(self.client.get(self.url).json(), body)
        draft = WaypointReportDraft.objects.get(signaling_point=self.point)
        self.assertEqual(draft.inspection_date.isoformat(), "2026-10-27")

    def test_partial_update_preserves_omitted_fields_and_creation_timestamp(self):
        original = self.save({"study_reason": "Original", "pgts": ["Escola"]}).json()
        response = self.save({"inspection_address": "Novo endereço"}, revision=1)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["revision"], 2)
        self.assertEqual(body["fields"]["study_reason"], "Original")
        self.assertEqual(body["fields"]["pgts"], ["Escola"])
        self.assertEqual(body["created_at"], original["created_at"])
        self.assertEqual(WaypointReportDraft.objects.count(), 1)

    def test_incomplete_fields_and_explicit_clearing(self):
        self.assertEqual(self.save({"inspection_date": "2026-10-27", "study_reason": "x"}).status_code, 200)
        response = self.save({"inspection_date": "", "occurrence_date": None,
                              "study_reason": "", "pgts": []}, revision=1)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["fields"]["inspection_date"])
        self.assertEqual(response.json()["fields"]["inspector_name"], "")
        self.assertEqual(response.json()["fields"]["inspection_address"], "")

    def test_shared_read_and_sequential_edit_by_another_authorized_user(self):
        original = self.save({"study_reason": "Compartilhado"}).json()
        other = Client()
        other_user = authorize(other)
        self.assertEqual(other.get(self.url).json(), original)
        self.assertEqual(self.save({"study_reason": "Não"}, 1, client=other).status_code, 403)
        self.client.post(reverse("signaling:release-reservation", args=[self.point.pk]), **self.proof)
        other_proof = self.acquire(other, self.point)
        response = self.save({"study_reason": "Revisado"}, 1, client=other, proof=other_proof)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_by"], other_user.pk)
        self.assertEqual(self.client.get(self.url).json()["fields"]["study_reason"], "Revisado")

    def test_waypoints_are_isolated_and_proof_is_bound_to_point(self):
        self.save({"study_reason": "Primeiro"})
        other = SignalingPoint.objects.create(latitude=1, longitude=1, status="OK")
        url = reverse("signaling:report-draft", args=[other.pk])
        self.assertEqual(self.client.get(url).json()["revision"], 0)
        self.assertNotEqual(self.save({"study_reason": "Segundo"}, url=url).status_code, 200)
        proof = self.acquire(self.client, other)
        self.assertEqual(self.save({"study_reason": "Segundo"}, proof=proof, url=url).status_code, 200)
        self.assertEqual(self.client.get(self.url).json()["fields"]["study_reason"], "Primeiro")
        self.assertEqual(WaypointReportDraft.objects.count(), 2)

    def test_invalid_dates_text_types_and_limits_do_not_create_draft(self):
        invalid = [
            {"inspection_date": "2026-02-30"}, {"inspection_date": "27/10/2026"},
            {"inspection_date": 123}, {"study_reason": None}, {"study_reason": 123},
            {"inspection_address": "a"*301}, {"study_reason": "a"*2001},
            {"study_objective": "a"*2001}, {"functional_classification": "a"*501},
            {"geometric_configuration": "a"*501}, {"regulated_speed": "a"*101},
            {"inspector_name": "a"*201}, {"study_objective": "bad\x00text"},
            {"pgts": "Escola"}, {"pgts": [123]}, {"pgts": ["a"*301]},
            {"pgts": ["Escola"]*51}, {"pgts": ["bad\x01text"]},
        ]
        for values in invalid:
            with self.subTest(fields=list(values)):
                response = self.save(values)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(response.json()["code"], "invalid_draft_fields")
        self.assertFalse(WaypointReportDraft.objects.exists())

    def test_invalid_patch_is_atomic_and_preserves_revision(self):
        self.save({"study_reason": "Original"})
        response = self.save({"study_reason": "Mudança", "inspection_date": "invalid"}, 1)
        self.assertEqual(response.status_code, 400)
        body = self.client.get(self.url).json()
        self.assertEqual(body["revision"], 1)
        self.assertEqual(body["fields"]["study_reason"], "Original")

    def test_unknown_fields_files_credentials_and_server_metadata_are_rejected(self):
        for name in ("photos", "file", "token", "generation", "session", "updated_by",
                     "revision", "signaling_point", "created_at", "analysis_id"):
            with self.subTest(field=name):
                self.assertEqual(self.save({name: "not allowed"}).status_code, 400)
        response = self.client.post(self.url, {
            "expected_revision": 0, "fields": "{}",
            "photos": SimpleUploadedFile("photo.png", b"image", content_type="image/png"),
        }, **self.proof)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(WaypointReportDraft.objects.exists())

    def test_invalid_payloads_and_revision_types(self):
        for data in ([], None, {}, {"fields": {}},
                     {"expected_revision": 0, "fields": {}, "extra": 1}):
            response = self.client.post(self.url, json.dumps(data),
                content_type="application/json", **self.proof)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(self.url, "{", content_type="application/json", **self.proof).status_code, 400)
        for revision in (True, -1, "0", None, 1.0, 9223372036854775808):
            self.assertEqual(self.save({"study_reason": "x"}, revision).status_code, 400)
        self.assertEqual(self.save({}).status_code, 400)
        self.assertFalse(WaypointReportDraft.objects.exists())

    def test_missing_invalid_expired_and_released_reservations(self):
        self.assertEqual(self.save({"study_reason": "x"}, proof={}).status_code, 428)
        bad = {**self.proof, "HTTP_X_WAYPOINT_TOKEN": "a"*43}
        self.assertEqual(self.save({"study_reason": "x"}, proof=bad).status_code, 403)
        bad_interaction = {**self.proof, "HTTP_X_WAYPOINT_INTERACTION": str(uuid4())}
        self.assertEqual(self.save({"study_reason": "x"}, proof=bad_interaction).status_code, 403)
        self.expire()
        response = self.save({"study_reason": "x"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "reservation_expired")
        self.proof = self.acquire(self.client, self.point)
        self.client.post(reverse("signaling:release-reservation", args=[self.point.pk]), **self.proof)
        response = self.save({"study_reason": "x"})
        self.assertEqual(response.json()["code"], "reservation_inactive")
        self.assertFalse(WaypointReportDraft.objects.exists())

    def test_previous_generation_cannot_overwrite_draft(self):
        self.save({"study_reason": "Original"})
        self.expire()
        new_proof = self.acquire(self.client, self.point)
        response = self.save({"study_reason": "Obsoleto"}, 1)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "reservation_generation_stale")
        self.assertEqual(self.save({"study_reason": "Atual"}, 1, proof=new_proof).status_code, 200)

    def test_revision_conflict_preserves_latest_values(self):
        self.save({"study_reason": "Atual"})
        for revision in (0, 2):
            response = self.save({"study_reason": "Obsoleto"}, revision)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["code"], "draft_revision_conflict")
            self.assertEqual(response.json()["revision"], 1)
        self.assertEqual(self.client.get(self.url).json()["fields"]["study_reason"], "Atual")

    def test_authentication_permissions_and_csrf(self):
        anonymous = Client()
        for method in ("get", "post"):
            self.assertEqual(getattr(anonymous, method)(self.url).status_code, 401)
        for permissions in ((), ("view_signalingpoint",), ("generate_signaling_report",)):
            client = Client()
            authorize(client, permissions)
            self.assertEqual(client.get(self.url).status_code, 403)
            self.assertEqual(self.save({"study_reason": "x"}, client=client).status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(self.url, {}, content_type="application/json", **self.proof)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")
        self.client.get("/")
        csrf_client.cookies["csrftoken"] = self.client.cookies["csrftoken"].value
        # Use the original authenticated session, since proof is session-bound.
        from django.conf import settings
        csrf_client.cookies[settings.SESSION_COOKIE_NAME] = self.client.session.session_key
        response = csrf_client.post(self.url, {"expected_revision": 0, "fields": {"study_reason": "x"}},
            content_type="application/json", HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
            **self.proof)
        self.assertEqual(response.status_code, 200, response.content)

    def test_unknown_point_returns_json_404_and_query_secrets_are_rejected(self):
        url = reverse("signaling:report-draft", args=[self.point.pk+999])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.save({"study_reason": "x"}, url=url).status_code, 404)
        self.assertEqual(self.client.get(self.url+"?token=secret").status_code, 400)

    def test_revoked_permission_and_logged_out_session_cannot_write(self):
        self.user.user_permissions.clear()
        self.assertEqual(self.save({"study_reason": "x"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.save({"study_reason": "x"}).status_code, 401)
        self.assertFalse(WaypointReportDraft.objects.exists())

    def test_revision_overflow_fails_without_mutation(self):
        self.save({"study_reason": "Original"})
        WaypointReportDraft.objects.update(revision=9223372036854775807)
        response = self.save({"study_reason": "Mudança"}, 9223372036854775807)
        self.assertEqual(response.status_code, 400)
        draft = WaypointReportDraft.objects.get(signaling_point=self.point)
        self.assertEqual(draft.revision, 9223372036854775807)
        self.assertEqual(draft.study_reason, "Original")

    def test_database_enforces_one_draft_and_positive_revision(self):
        self.save({"study_reason": ""})
        with self.assertRaises(IntegrityError), transaction.atomic():
            WaypointReportDraft.objects.create(signaling_point=self.point)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WaypointReportDraft.objects.update(revision=0)
        self.assertEqual(WaypointReportDraft.objects.get().revision, 1)

    def test_author_deletion_preserves_draft_and_waypoint_deletion_removes_it(self):
        self.save({"study_reason": "Preservado"})
        self.user.delete()
        draft = WaypointReportDraft.objects.get(signaling_point=self.point)
        self.assertIsNone(draft.updated_by_id)
        self.assertEqual(draft.study_reason, "Preservado")
        self.point.delete()
        self.assertFalse(WaypointReportDraft.objects.exists())


class ReportDraftMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_waypoint_generation_and_children(self):
        before = ("signaling", "0009_waypoint_reservation")
        after = ("signaling", "0010_waypoint_report_draft")
        try:
            executor = MigrationExecutor(connection)
            executor.migrate([before])
            apps = executor.loader.project_state([before]).apps
            point = apps.get_model("signaling", "SignalingPoint").objects.create(
                latitude="-21.17", longitude="-47.81", status="OK", reservation_generation=7,
            )
            apps.get_model("signaling", "SignalingIntervention").objects.create(
                signaling_point=point, type="R1", condition="OK", notes="Preservado",
            )
            executor = MigrationExecutor(connection)
            executor.migrate([after])
            apps = executor.loader.project_state([after]).apps
            restored = apps.get_model("signaling", "SignalingPoint").objects.get(pk=point.pk)
            self.assertEqual(restored.reservation_generation, 7)
            self.assertEqual(restored.interventions.get().notes, "Preservado")
            Draft = apps.get_model("signaling", "WaypointReportDraft")
            self.assertFalse(Draft.objects.exists())
            draft = Draft.objects.create(signaling_point=restored)
            self.assertEqual(draft.revision, 1)
            self.assertEqual(draft.pgts, [])
            self.assertIsNone(draft.inspection_date)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
