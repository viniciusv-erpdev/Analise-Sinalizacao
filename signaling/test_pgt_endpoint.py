from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from signaling.models import SignalingIntervention, SignalingPoint
from signaling.overpass import OverpassUnavailable, PGT_SEARCH_ERROR


class PGTEndpointTests(TestCase):
    def setUp(self):
        self.point = SignalingPoint.objects.create(
            latitude="-21.170123", longitude="-47.810456",
            status="OK", search_radius_meters=120,
        )
        self.url = reverse("signaling:search-point-pgts", args=[self.point.pk])
        self.search = patch("signaling.views.find_nearby_pgts", return_value=["🏥 Unidade de Saúde: Hospital X"]).start()
        self.addCleanup(patch.stopall)

    def test_public_access_matches_current_report_and_ignores_client_coordinates(self):
        response = self.client.post(self.url, {
            "latitude": 80, "longitude": 90, "radius_meters": 99999,
            "year": 2020, "gravity": "fatal",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "success": True, "results": ["🏥 Unidade de Saúde: Hospital X"],
        })
        self.point.refresh_from_db()
        self.search.assert_called_once_with(
            latitude=self.point.latitude, longitude=self.point.longitude,
            radius_meters=120,
        )

    def test_authenticated_user_has_same_access(self):
        user = get_user_model().objects.create_user(username="report-user")
        self.client.force_login(user)
        self.assertEqual(self.client.post(self.url).status_code, 200)

    def test_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post(self.url).status_code, 403)
        report_url = reverse("signaling:point-report", args=[self.point.pk])
        from signaling.surveys import ANALYSIS_SESSION_KEY
        session = csrf_client.session
        session[ANALYSIS_SESSION_KEY] = {"view_mode": "individual", "map_data": []}
        session.save()
        csrf_client.get(report_url)
        token = csrf_client.cookies["csrftoken"].value
        self.assertEqual(csrf_client.post(self.url, HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_missing_waypoint_returns_json_without_query(self):
        response = self.client.post(reverse("signaling:search-point-pgts", args=[999999]))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["success"])
        self.search.assert_not_called()

    def test_invalid_persisted_coordinates_return_controlled_error(self):
        # Usar o service real para validar o valor inválido, mantendo HTTP mockado.
        from signaling.overpass import find_nearby_pgts
        self.search.side_effect = find_nearby_pgts
        SignalingPoint.objects.filter(pk=self.point.pk).update(latitude=91)
        with patch("signaling.overpass.urlopen") as http:
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        http.assert_not_called()

    def test_failure_returns_friendly_json(self):
        self.search.side_effect = OverpassUnavailable("internal detail")
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"success": False, "error": PGT_SEARCH_ERROR})
        self.assertNotContains(response, "internal detail", status_code=503)

    def test_search_does_not_change_database_or_session(self):
        before = list(SignalingPoint.objects.values())
        interventions = list(SignalingIntervention.objects.values())
        session = dict(self.client.session)
        self.client.post(self.url)
        self.assertEqual(list(SignalingPoint.objects.values()), before)
        self.assertEqual(list(SignalingIntervention.objects.values()), interventions)
        self.assertEqual(dict(self.client.session), session)
