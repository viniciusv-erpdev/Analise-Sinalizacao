import json
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from signaling.models import SignalingPoint, SignalingIntervention
from signaling.test_support import authorize


class WaypointSynchronizationTests(TestCase):
    def setUp(self):
        self.url = reverse("signaling:synchronize-points")
        self.client = Client()
        authorize(self.client, ("view_signalingpoint",))

    def sync(self, known=None, client=None):
        return (client or self.client).post(
            self.url, json.dumps({"known": known or {}}), content_type="application/json")

    def point(self):
        return SignalingPoint.objects.create(latitude=0, longitude=0, status="OK")

    def test_creation_update_deletion_and_unchanged_inventory(self):
        point = self.point()
        first = self.sync().json()
        item = first["upserts"][0]
        known = {str(point.pk): item["revision"]}
        self.assertEqual(self.sync(known).json()["upserts"], [])
        point.status = "ABSENT"
        point.save(update_fields=["status"])  # deliberately no timestamp update
        changed = self.sync(known).json()["upserts"][0]
        self.assertEqual(changed["point"]["status"], "ABSENT")
        self.assertNotEqual(item["revision"], changed["revision"])
        point.delete()
        self.assertEqual(self.sync(known).json()["deleted"], [int(next(iter(known)))])

    def test_interventions_change_hash_without_touching_parent_timestamp(self):
        point = self.point()
        item = self.sync().json()["upserts"][0]
        SignalingIntervention.objects.create(signaling_point=point, type="R1", condition="OK")
        changed = self.sync({str(point.pk): item["revision"]}).json()["upserts"][0]
        self.assertNotEqual(changed["revision"], item["revision"])
        self.assertEqual(len(changed["point"]["interventions"]), 1)

    def test_two_clients_see_committed_new_point_without_reload(self):
        other = Client()
        authorize(other, ("view_signalingpoint",))
        self.assertEqual(self.sync(client=other).json()["upserts"], [])
        creator = Client()
        authorize(creator, ("view_signalingpoint", "add_signalingpoint"))
        created = creator.post(reverse("signaling:create-point"),
                               json.dumps({"latitude": 0, "longitude": 0, "status": "OK"}),
                               content_type="application/json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.sync(client=other).json()["upserts"][0]["point"]["id"], created.json()["id"])

    def test_authorization_and_csrf(self):
        self.assertEqual(self.sync(client=Client()).status_code, 401)
        denied = Client()
        authorize(denied, ())
        self.assertEqual(self.sync(client=denied).status_code, 403)
        csrf = Client(enforce_csrf_checks=True)
        authorize(csrf, ("view_signalingpoint",))
        self.assertEqual(self.sync(client=csrf).status_code, 403)
        csrf.cookies["csrftoken"] = "a" * 32
        response = csrf.post(self.url, '{"known":{}}', content_type="application/json",
                             HTTP_X_CSRFTOKEN="a" * 32)
        self.assertEqual(response.status_code, 200)

    def test_invalid_inventory_and_no_secret_or_reservation_calls(self):
        self.point()
        for data in ([], {}, {"known":[]}, {"known":{"1":"secret"}}, {"known":{}, "token":"secret"}):
            response = self.client.post(self.url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 400)
        with patch("signaling.reservations.acquire_reservation") as acquire, \
                patch("signaling.reservations.release_reservation") as release:
            response = self.sync()
        acquire.assert_not_called()
        release.assert_not_called()
        self.assertEqual(response["Cache-Control"], "private, no-store")
        for secret in ("token", "reservation_generation", "session_key", "interaction_id"):
            self.assertNotIn(secret, response.content.decode())
