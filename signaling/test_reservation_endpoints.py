"""HTTP contracts. SQLite unit fixtures do not claim PostgreSQL exclusivity."""
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from signaling import reservations as r
from signaling.models import SignalingPoint, SignalingIntervention, SignalingPointProblem
from signaling.test_support import authorize


class ReservationEndpointTests(TestCase):
    def setUp(self):
        if connection.vendor == "sqlite":
            guard = patch("signaling.reservations._require_locking_backend")
            guard.start()
            self.addCleanup(guard.stop)
        self.client = Client(enforce_csrf_checks=True)
        self.user = authorize(self.client)
        self.point = SignalingPoint.objects.create(latitude=0, longitude=0, status="OK")
        self.intervention = SignalingIntervention.objects.create(
            signaling_point=self.point, type="R1", condition="OK")
        self.problem = SignalingPointProblem.objects.create(
            signaling_point=self.point, problem_code="P1")
        self.client.get("/")
        self.csrf = self.client.cookies["csrftoken"].value

    def url(self, action):
        return reverse("signaling:" + action, args=[self.point.pk])

    def post(self, action, payload=None, headers=None, client=None):
        return (client or self.client).post(self.url(action), payload or {},
            content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf, **(headers or {}))

    def acquire(self, interaction=None):
        response = self.post("acquire-reservation", {"interaction_id": str(interaction or uuid4())})
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        return {
            "HTTP_X_WAYPOINT_TOKEN": data["token"],
            "HTTP_X_WAYPOINT_INTERACTION": data["interaction_id"],
            "HTTP_X_WAYPOINT_GENERATION": str(data["generation"]),
        }

    def test_acquisition_same_session_tabs_conflict_and_status_does_not_leak_proof(self):
        proof = self.acquire()
        conflict = self.post("acquire-reservation", {"interaction_id": str(uuid4())})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "reservation_occupied")
        without = self.client.get(self.url("reservation-status"))
        own = self.client.get(self.url("reservation-status"), **proof)
        self.assertEqual(without.json()["state"], "reserved_other")
        self.assertEqual(own.json()["state"], "reserved_self")
        self.assertNotIn("token", own.json())
        self.assertNotIn("session_digest", own.json())
        self.assertIn("no-store", own["Cache-Control"])

    def test_renew_release_and_repeat_require_full_interaction_proof(self):
        proof = self.acquire()
        bad = {**proof, "HTTP_X_WAYPOINT_INTERACTION": str(uuid4())}
        for action in ["renew-reservation", "release-reservation"]:
            response = self.post(action, headers=bad)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "reservation_credentials_invalid")
        self.assertEqual(self.post("renew-reservation", headers=proof).status_code, 200)
        self.assertTrue(self.post("release-reservation", headers=proof).json()["released"])
        self.assertTrue(self.post("release-reservation", headers=proof).json()["released"])
        self.assertEqual(self.client.get(self.url("reservation-status")).json()["state"], "available")

    def test_mutations_all_require_reservation_and_preserve_authorized_reads(self):
        operations = [
            ("update-point-status", [self.point.pk], {"status": "ABSENT"}),
            ("update-point-search-radius", [self.point.pk], {"search_radius_meters": 80}),
            ("delete-point", [self.point.pk], {}),
            ("save-intervention", [self.point.pk], {"type": "R1", "condition": "OK"}),
            ("update-intervention-condition", [self.point.pk, self.intervention.pk], {"condition": "ABSENT"}),
            ("update-intervention-notes", [self.point.pk, self.intervention.pk], {"notes": "x"}),
            ("delete-intervention", [self.point.pk, self.intervention.pk], {}),
            ("point-problems", [self.point.pk], {"problem_code": "P2", "solution_codes": ["P2A"]}),
            ("update-problem-solution", [self.point.pk, self.problem.pk], {"solution_codes": ["P1A"]}),
            ("delete-point-problem", [self.point.pk, self.problem.pk], {}),
        ]
        for name, args, data in operations:
            with self.subTest(endpoint=name):
                response = self.client.post(reverse("signaling:"+name, args=args),
                    data, content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf)
                self.assertEqual(response.status_code, 428)
                self.assertEqual(response.json()["code"], "reservation_required")
        self.assertEqual(self.client.get(self.url("point-problems")).status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertTrue(SignalingPoint.objects.filter(pk=self.point.pk).exists())

    def test_valid_reservation_allows_waypoint_and_related_mutations(self):
        proof = self.acquire()
        self.assertEqual(self.post("update-point-status", {"status": "ABSENT"}, proof).status_code, 200)
        response = self.client.post(reverse("signaling:update-intervention-notes",
            args=[self.point.pk, self.intervention.pk]), {"notes": "reserved edit"},
            content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf, **proof)
        self.assertEqual(response.status_code, 200)
        self.intervention.refresh_from_db()
        self.assertEqual(self.intervention.notes, "reserved edit")
        self.assertEqual(self.post("point-problems",
            {"problem_code": "P2", "solution_codes": ["P2A"]}, proof).status_code, 201)
        response = self.client.post(reverse("signaling:update-problem-solution",
            args=[self.point.pk, self.problem.pk]), {"solution_codes": ["P1A"]},
            content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf, **proof)
        self.assertEqual(response.status_code, 200)

    def test_expired_and_stale_tokens_never_modify_waypoint(self):
        proof = self.acquire()
        from signaling.models import WaypointReservation
        now = r._database_now()
        WaypointReservation.objects.update(acquired_at=now-timedelta(seconds=3),
            renewed_at=now-timedelta(seconds=2), expires_at=now-timedelta(seconds=1))
        response = self.post("update-point-status", {"status":"ABSENT"}, proof)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "reservation_expired")
        new = self.acquire()
        response = self.post("update-point-status", {"status":"ABSENT"}, proof)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "reservation_generation_stale")
        self.point.refresh_from_db()
        self.assertEqual(self.point.status, "OK")
        self.assertEqual(self.post("delete-point", headers=new).status_code, 200)
        self.assertFalse(SignalingPoint.objects.filter(pk=self.point.pk).exists())

    def test_other_user_and_session_cannot_edit_or_release(self):
        proof = self.acquire()
        for other_user in [self.user, None]:
            client = Client()
            if other_user:
                client.force_login(other_user)
            else:
                authorize(client)
            for action in ["update-point-status", "release-reservation"]:
                response = self.post(action, {"status":"ABSENT"}, proof, client=client)
                self.assertEqual(response.status_code, 403)

    def test_csrf_authorization_malformed_headers_and_url_secrets(self):
        response = self.client.post(self.url("acquire-reservation"),
            {"interaction_id":str(uuid4())}, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")
        unauthorized = Client()
        self.assertEqual(self.post("acquire-reservation",
            {"interaction_id":str(uuid4())}, client=unauthorized).status_code, 401)
        authorize(unauthorized, ())
        self.assertEqual(self.post("acquire-reservation",
            {"interaction_id":str(uuid4())}, client=unauthorized).status_code, 403)
        self.assertEqual(self.post("acquire-reservation", {"interaction_id":"invalid"}).status_code, 400)
        self.assertEqual(self.client.get(self.url("reservation-status")+"?token=not-accepted").status_code, 400)
        self.assertEqual(self.post("renew-reservation", headers={
            "HTTP_X_WAYPOINT_TOKEN":"a"*43}).status_code, 400)

    def test_reports_and_pgt_require_proof_before_work(self):
        with patch("signaling.views.find_nearby_pgts") as search:
            self.assertEqual(self.post("search-point-pgts").status_code, 428)
            search.assert_not_called()
        self.assertEqual(self.client.get(self.url("point-report")).status_code, 428)
        self.assertEqual(self.post("point-report").status_code, 428)

    def test_report_html_snapshot_and_final_fence(self):
        proof = self.acquire()
        session = self.client.session
        session["accident_analysis_state"] = {"view_mode":"individual", "map_data":[]}
        session.save()
        response = self.client.get(self.url("point-report"), **proof)
        self.assertEqual(response.status_code, 200)
        def release_during_work(*args):
            self.post("release-reservation", headers=proof)
            self.acquire()
            return None
        with patch("signaling.views.build_accident_types_chart_data_uri",
                   side_effect=release_during_work):
            response = self.client.get(self.url("point-report"), **proof)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "reservation_generation_stale")

    def test_pgt_runs_outside_validation_and_rechecks_fencing(self):
        proof = self.acquire()
        def external_work(**kwargs):
            self.post("release-reservation", headers=proof)
            self.acquire()
            return ["discarded result"]
        with patch("signaling.views.find_nearby_pgts", side_effect=external_work):
            response = self.post("search-point-pgts", headers=proof)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("results", response.json())

    def test_docx_has_no_validation_transaction_during_generation_and_discards_stale_buffer(self):
        from io import BytesIO
        proof = self.acquire()
        session = self.client.session
        session["accident_analysis_state"] = {"view_mode":"individual", "map_data":[]}
        session.save()
        form_data = {
            "inspection_address":"Rua X", "inspection_date":"2026-10-21",
            "inspector_name":"Inspector", "functional_classification":"Via arterial",
            "geometric_configuration":"Cruzamento", "regulated_speed":"50 km/h",
        }
        buffer = BytesIO(b"generated-docx")
        baseline = len(connection.savepoint_ids)

        def generate(point, survey, *args, author):
            self.assertEqual(author.pk, self.user.pk)
            self.assertEqual(len(connection.savepoint_ids), baseline)
            self.assertEqual(survey["interventions"][0]["notes"], "")
            self.post("release-reservation", headers=proof)
            self.acquire()
            return buffer

        with patch("signaling.views.generate_signaling_report", side_effect=generate):
            response = self.client.post(self.url("point-report"), form_data,
                HTTP_X_CSRFTOKEN=self.csrf, **proof)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "reservation_generation_stale")
        self.assertTrue(buffer.closed)

    def test_report_snapshot_is_not_reloaded_during_processing(self):
        proof = self.acquire()
        session = self.client.session
        session["accident_analysis_state"] = {"view_mode":"individual", "map_data":[]}
        session.save()
        from signaling.surveys import build_signaling_survey_from_items
        def build(point, accidents, *, point_items):
            # Domain data are already materialized. This processing performs no SQL.
            with self.assertNumQueries(0):
                return build_signaling_survey_from_items(point, accidents, point_items=point_items)
        with patch("signaling.views.build_signaling_survey_from_items", side_effect=build):
            self.assertEqual(self.client.get(self.url("point-report"), **proof).status_code, 200)

    def test_admin_superuser_cannot_write_or_bulk_delete(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        for model, pk in [("signalingpoint",self.point.pk),
                          ("signalingintervention",self.intervention.pk)]:
            self.client.get("/")
            csrf = self.client.cookies["csrftoken"].value
            for suffix, args in [("add",[]),("change",[pk]),("delete",[pk])]:
                response = self.client.post(reverse("admin:signaling_"+model+"_"+suffix,
                    args=args), {"post":"yes"}, HTTP_X_CSRFTOKEN=csrf)
                self.assertEqual(response.status_code, 403)
            self.client.post(reverse("admin:signaling_"+model+"_changelist"),
                {"action":"delete_selected","_selected_action":[pk],"post":"yes"},
                HTTP_X_CSRFTOKEN=csrf)
        self.assertTrue(SignalingPoint.objects.filter(pk=self.point.pk).exists())
        self.assertTrue(SignalingIntervention.objects.filter(pk=self.intervention.pk).exists())
