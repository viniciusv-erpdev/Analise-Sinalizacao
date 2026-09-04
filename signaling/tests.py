from decimal import Decimal
import json

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from signaling.models import SignalingIntervention, SignalingPoint


class SignalingPointTests(TestCase):
    def create_point(self, status: str = SignalingPoint.Status.OK) -> SignalingPoint:
        return SignalingPoint.objects.create(
            latitude=Decimal("-21.170000"),
            longitude=Decimal("-47.810000"),
            status=status,
        )

    def test_creates_point_with_ok_status(self):
        point = self.create_point(SignalingPoint.Status.OK)

        self.assertEqual(point.status, SignalingPoint.Status.OK)

    def test_creates_point_with_incomplete_status(self):
        point = self.create_point(SignalingPoint.Status.INCOMPLETE)

        self.assertEqual(point.status, SignalingPoint.Status.INCOMPLETE)

    def test_creates_point_with_absent_status(self):
        point = self.create_point(SignalingPoint.Status.ABSENT)

        self.assertEqual(point.status, SignalingPoint.Status.ABSENT)

    def test_persists_point_through_orm(self):
        point = self.create_point()

        persisted_point = SignalingPoint.objects.get(pk=point.pk)

        self.assertEqual(persisted_point.latitude, Decimal("-21.170000"))
        self.assertEqual(persisted_point.longitude, Decimal("-47.810000"))
        self.assertIsNotNone(persisted_point.created_at)
        self.assertIsNotNone(persisted_point.updated_at)

    def test_rejects_invalid_status_during_model_validation(self):
        point = SignalingPoint(
            latitude=Decimal("-21.170000"),
            longitude=Decimal("-47.810000"),
            status="INVALID",
        )

        with self.assertRaises(ValidationError):
            point.full_clean()

    def test_rejects_latitude_outside_valid_range(self):
        point = SignalingPoint(
            latitude=Decimal("91"),
            longitude=Decimal("-47.810000"),
            status=SignalingPoint.Status.OK,
        )

        with self.assertRaises(ValidationError):
            point.full_clean()

    def test_rejects_longitude_outside_valid_range(self):
        point = SignalingPoint(
            latitude=Decimal("-21.170000"),
            longitude=Decimal("181"),
            status=SignalingPoint.Status.OK,
        )

        with self.assertRaises(ValidationError):
            point.full_clean()


class SignalingInterventionTests(TestCase):
    def setUp(self):
        self.point = SignalingPoint.objects.create(
            latitude=Decimal("-21.170000"),
            longitude=Decimal("-47.810000"),
            status=SignalingPoint.Status.INCOMPLETE,
        )

    def create_intervention(
        self,
        condition: str = SignalingIntervention.Condition.OK,
    ) -> SignalingIntervention:
        return SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=condition,
        )

    def test_creates_traffic_light_intervention(self):
        intervention = self.create_intervention()

        self.assertEqual(
            intervention.type,
            SignalingIntervention.Type.TRAFFIC_LIGHT,
        )

    def test_creates_intervention_with_ok_condition(self):
        intervention = self.create_intervention(SignalingIntervention.Condition.OK)

        self.assertEqual(intervention.condition, SignalingIntervention.Condition.OK)

    def test_creates_intervention_with_absent_condition(self):
        intervention = self.create_intervention(
            SignalingIntervention.Condition.ABSENT,
        )

        self.assertEqual(
            intervention.condition,
            SignalingIntervention.Condition.ABSENT,
        )

    def test_point_exposes_related_interventions(self):
        intervention = self.create_intervention()

        self.assertSequenceEqual(
            self.point.interventions.all(),
            [intervention],
        )

    def test_deleting_point_cascades_to_interventions(self):
        intervention = self.create_intervention()

        self.point.delete()

        self.assertFalse(
            SignalingIntervention.objects.filter(pk=intervention.pk).exists(),
        )

    def test_rejects_invalid_type_during_model_validation(self):
        intervention = SignalingIntervention(
            signaling_point=self.point,
            type="INVALID",
            condition=SignalingIntervention.Condition.OK,
        )

        with self.assertRaises(ValidationError):
            intervention.full_clean()

    def test_rejects_invalid_condition_during_model_validation(self):
        intervention = SignalingIntervention(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition="INVALID",
        )

        with self.assertRaises(ValidationError):
            intervention.full_clean()


class SignalingPointEndpointTests(TestCase):
    def setUp(self):
        self.create_url = reverse("signaling:create-point")

    def create_point(self) -> SignalingPoint:
        return SignalingPoint.objects.create(
            latitude=Decimal("-21.170000"),
            longitude=Decimal("-47.810000"),
            status=SignalingPoint.Status.OK,
        )

    def post_json(self, url: str, data: dict[str, object]):
        return self.client.post(
            url,
            data=json.dumps(data),
            content_type="application/json",
        )

    def valid_payload(self) -> dict[str, object]:
        return {
            "latitude": -21.17,
            "longitude": -47.81,
            "status": SignalingPoint.Status.INCOMPLETE,
        }

    def test_map_get_includes_persisted_points_in_separate_payload(self):
        point = self.create_point()

        response = self.client.get(reverse("analysis"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["signaling_map_data"],
            [{
                "id": point.id,
                "latitude": -21.17,
                "longitude": -47.81,
                "status": SignalingPoint.Status.OK,
                "interventions": [],
            }],
        )

    def test_creates_valid_point(self):
        response = self.post_json(self.create_url, self.valid_payload())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], SignalingPoint.Status.INCOMPLETE)
        self.assertEqual(SignalingPoint.objects.count(), 1)

    def test_creates_point_for_each_status_with_leaflet_coordinates(self):
        statuses = (
            SignalingPoint.Status.OK,
            SignalingPoint.Status.INCOMPLETE,
            SignalingPoint.Status.ABSENT,
        )

        for status in statuses:
            with self.subTest(status=status):
                response = self.post_json(
                    self.create_url,
                    {
                        "latitude": -21.1775123456789,
                        "longitude": -47.8103123456789,
                        "status": status,
                    },
                )

                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["status"], status)

        self.assertEqual(SignalingPoint.objects.count(), 3)
        persisted_point = SignalingPoint.objects.order_by("id").first()
        self.assertEqual(persisted_point.latitude, Decimal("-21.177512"))
        self.assertEqual(persisted_point.longitude, Decimal("-47.810312"))

    def test_rejects_invalid_status(self):
        payload = self.valid_payload()
        payload["status"] = "INVALID"

        response = self.post_json(self.create_url, payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json()["errors"])

    def test_rejects_invalid_latitude(self):
        payload = self.valid_payload()
        payload["latitude"] = 91

        response = self.post_json(self.create_url, payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("latitude", response.json()["errors"])

    def test_rejects_invalid_longitude(self):
        payload = self.valid_payload()
        payload["longitude"] = -181

        response = self.post_json(self.create_url, payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("longitude", response.json()["errors"])

    def test_deletes_existing_point(self):
        point = self.create_point()
        delete_url = reverse("signaling:delete-point", args=[point.id])

        response = self.post_json(delete_url, {})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SignalingPoint.objects.filter(pk=point.pk).exists())

    def test_returns_not_found_when_deleting_missing_point(self):
        delete_url = reverse("signaling:delete-point", args=[999])

        response = self.post_json(delete_url, {})

        self.assertEqual(response.status_code, 404)

    def test_get_does_not_delete_point(self):
        point = self.create_point()
        delete_url = reverse("signaling:delete-point", args=[point.id])

        response = self.client.get(delete_url)

        self.assertEqual(response.status_code, 405)
        self.assertTrue(SignalingPoint.objects.filter(pk=point.pk).exists())

    def test_created_point_persists_in_later_query(self):
        create_response = self.post_json(self.create_url, self.valid_payload())

        response = self.client.get(reverse("analysis"))

        point_data = response.context["signaling_map_data"][0]
        self.assertEqual(point_data["id"], create_response.json()["id"])
        self.assertEqual(point_data["status"], SignalingPoint.Status.INCOMPLETE)

    def test_updates_ok_status_to_incomplete(self):
        point = self.create_point()

        response = self.post_json(
            reverse("signaling:update-point-status", args=[point.id]),
            {"status": SignalingPoint.Status.INCOMPLETE},
        )

        point.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(point.status, SignalingPoint.Status.INCOMPLETE)

    def test_updates_incomplete_status_to_absent(self):
        point = self.create_point()
        point.status = SignalingPoint.Status.INCOMPLETE
        point.save()

        response = self.post_json(
            reverse("signaling:update-point-status", args=[point.id]),
            {"status": SignalingPoint.Status.ABSENT},
        )

        point.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(point.status, SignalingPoint.Status.ABSENT)

    def test_updates_absent_status_to_ok(self):
        point = self.create_point()
        point.status = SignalingPoint.Status.ABSENT
        point.save()

        response = self.post_json(
            reverse("signaling:update-point-status", args=[point.id]),
            {"status": SignalingPoint.Status.OK},
        )

        point.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(point.status, SignalingPoint.Status.OK)

    def test_rejects_invalid_point_status_update(self):
        point = self.create_point()

        response = self.post_json(
            reverse("signaling:update-point-status", args=[point.id]),
            {"status": "INVALID"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json()["errors"])

    def test_returns_not_found_when_updating_missing_point(self):
        response = self.post_json(
            reverse("signaling:update-point-status", args=[999]),
            {"status": SignalingPoint.Status.OK},
        )

        self.assertEqual(response.status_code, 404)

    def test_updating_status_does_not_change_other_point(self):
        point = self.create_point()
        other_point = SignalingPoint.objects.create(
            latitude=Decimal("-21.180000"),
            longitude=Decimal("-47.820000"),
            status=SignalingPoint.Status.ABSENT,
        )

        self.post_json(
            reverse("signaling:update-point-status", args=[point.id]),
            {"status": SignalingPoint.Status.INCOMPLETE},
        )

        other_point.refresh_from_db()
        self.assertEqual(other_point.status, SignalingPoint.Status.ABSENT)


class SignalingInterventionEndpointTests(TestCase):
    def setUp(self):
        self.point = SignalingPoint.objects.create(
            latitude=Decimal("-21.170000"),
            longitude=Decimal("-47.810000"),
            status=SignalingPoint.Status.INCOMPLETE,
        )
        self.url = reverse(
            "signaling:save-intervention",
            args=[self.point.id],
        )

    def post_intervention(self, intervention_type: str, condition: str):
        return self.client.post(
            self.url,
            data=json.dumps({
                "type": intervention_type,
                "condition": condition,
            }),
            content_type="application/json",
        )

    def update_condition(
        self,
        intervention: SignalingIntervention,
        condition: str,
    ):
        return self.client.post(
            reverse(
                "signaling:update-intervention-condition",
                args=[self.point.id, intervention.id],
            ),
            data=json.dumps({"condition": condition}),
            content_type="application/json",
        )

    def test_adds_traffic_light_with_ok_condition(self):
        response = self.post_intervention(
            SignalingIntervention.Type.TRAFFIC_LIGHT,
            SignalingIntervention.Condition.OK,
        )

        self.assertEqual(response.status_code, 201)
        intervention = SignalingIntervention.objects.get()
        self.assertEqual(intervention.signaling_point, self.point)
        self.assertEqual(intervention.condition, SignalingIntervention.Condition.OK)

    def test_adds_traffic_light_with_absent_condition(self):
        response = self.post_intervention(
            SignalingIntervention.Type.TRAFFIC_LIGHT,
            SignalingIntervention.Condition.ABSENT,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            SignalingIntervention.objects.get().condition,
            SignalingIntervention.Condition.ABSENT,
        )

    def test_intervention_persists_in_later_map_query(self):
        response = self.post_intervention(
            SignalingIntervention.Type.TRAFFIC_LIGHT,
            SignalingIntervention.Condition.OK,
        )

        map_response = self.client.get(reverse("analysis"))

        intervention_data = map_response.context["signaling_map_data"][0][
            "interventions"
        ][0]
        self.assertEqual(intervention_data["id"], response.json()["id"])
        self.assertEqual(
            intervention_data["type"],
            SignalingIntervention.Type.TRAFFIC_LIGHT,
        )

    def test_creates_two_traffic_lights_for_same_point(self):
        first_response = self.post_intervention(
            SignalingIntervention.Type.TRAFFIC_LIGHT,
            SignalingIntervention.Condition.OK,
        )
        second_response = self.post_intervention(
            SignalingIntervention.Type.TRAFFIC_LIGHT,
            SignalingIntervention.Condition.ABSENT,
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)
        self.assertNotEqual(first_response.json()["id"], second_response.json()["id"])
        self.assertEqual(SignalingIntervention.objects.count(), 2)

    def test_creates_two_traffic_lights_with_same_condition(self):
        first_response = self.post_intervention(
            SignalingIntervention.Type.TRAFFIC_LIGHT,
            SignalingIntervention.Condition.OK,
        )
        second_response = self.post_intervention(
            SignalingIntervention.Type.TRAFFIC_LIGHT,
            SignalingIntervention.Condition.OK,
        )

        self.assertNotEqual(first_response.json()["id"], second_response.json()["id"])
        self.assertEqual(SignalingIntervention.objects.count(), 2)

    def test_creates_each_valid_intervention_type(self):
        for intervention_type in SignalingIntervention.Type.values:
            with self.subTest(intervention_type=intervention_type):
                response = self.post_intervention(
                    intervention_type,
                    SignalingIntervention.Condition.OK,
                )

                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["type"], intervention_type)

        self.assertEqual(
            SignalingIntervention.objects.count(),
            len(SignalingIntervention.Type.values),
        )

    def test_creates_three_speed_bumps_with_different_ids(self):
        responses = [
            self.post_intervention(
                SignalingIntervention.Type.SPEED_BUMP,
                SignalingIntervention.Condition.OK,
            )
            for _ in range(3)
        ]

        intervention_ids = {response.json()["id"] for response in responses}
        self.assertEqual(len(intervention_ids), 3)
        self.assertEqual(
            SignalingIntervention.objects.filter(
                type=SignalingIntervention.Type.SPEED_BUMP,
            ).count(),
            3,
        )

    def test_different_types_coexist_on_same_point(self):
        intervention_types = (
            SignalingIntervention.Type.TRAFFIC_LIGHT,
            SignalingIntervention.Type.SPEED_BUMP,
            SignalingIntervention.Type.RAISED_CROSSWALK,
        )

        for intervention_type in intervention_types:
            self.post_intervention(
                intervention_type,
                SignalingIntervention.Condition.OK,
            )

        self.assertSetEqual(
            set(self.point.interventions.values_list("type", flat=True)),
            set(intervention_types),
        )

    def test_two_points_can_each_have_a_traffic_light(self):
        other_point = SignalingPoint.objects.create(
            latitude=Decimal("-21.180000"),
            longitude=Decimal("-47.820000"),
            status=SignalingPoint.Status.OK,
        )
        SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
        )
        SignalingIntervention.objects.create(
            signaling_point=other_point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
        )

        self.assertEqual(SignalingIntervention.objects.count(), 2)

    def test_rejects_invalid_type(self):
        response = self.post_intervention(
            "INVALID",
            SignalingIntervention.Condition.OK,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("type", response.json()["errors"])

    def test_rejects_invalid_condition(self):
        response = self.post_intervention(
            SignalingIntervention.Type.TRAFFIC_LIGHT,
            "INVALID",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("condition", response.json()["errors"])

    def test_returns_not_found_for_missing_point(self):
        missing_point_url = reverse(
            "signaling:save-intervention",
            args=[999],
        )

        response = self.client.post(
            missing_point_url,
            data=json.dumps({
                "type": SignalingIntervention.Type.TRAFFIC_LIGHT,
                "condition": SignalingIntervention.Condition.OK,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_deletes_only_the_intervention(self):
        intervention = SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
        )
        delete_url = reverse(
            "signaling:delete-intervention",
            args=[self.point.id, intervention.id],
        )

        response = self.client.post(delete_url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SignalingIntervention.objects.exists())
        self.assertTrue(SignalingPoint.objects.filter(pk=self.point.pk).exists())

    def test_deleting_one_of_three_keeps_the_other_two(self):
        interventions = [
            SignalingIntervention.objects.create(
                signaling_point=self.point,
                type=SignalingIntervention.Type.SPEED_BUMP,
                condition=SignalingIntervention.Condition.OK,
            )
            for _ in range(3)
        ]
        delete_url = reverse(
            "signaling:delete-intervention",
            args=[self.point.id, interventions[1].id],
        )

        response = self.client.post(delete_url)

        self.assertEqual(response.status_code, 200)
        self.assertSetEqual(
            set(self.point.interventions.values_list("id", flat=True)),
            {interventions[0].id, interventions[2].id},
        )

    def test_updates_ok_condition_to_absent(self):
        intervention = SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
        )

        response = self.update_condition(
            intervention,
            SignalingIntervention.Condition.ABSENT,
        )

        intervention.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(intervention.condition, SignalingIntervention.Condition.ABSENT)

    def test_updates_absent_condition_to_ok(self):
        intervention = SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.ABSENT,
        )

        response = self.update_condition(
            intervention,
            SignalingIntervention.Condition.OK,
        )

        intervention.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(intervention.condition, SignalingIntervention.Condition.OK)

    def test_rejects_invalid_condition_update(self):
        intervention = SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
        )

        response = self.update_condition(intervention, "INVALID")

        self.assertEqual(response.status_code, 400)
        self.assertIn("condition", response.json()["errors"])

    def test_returns_not_found_when_updating_missing_intervention(self):
        response = self.client.post(
            reverse(
                "signaling:update-intervention-condition",
                args=[self.point.id, 999],
            ),
            data=json.dumps({"condition": SignalingIntervention.Condition.OK}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_updating_condition_does_not_change_other_intervention(self):
        intervention = SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
        )
        other_intervention = SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
        )

        self.update_condition(
            intervention,
            SignalingIntervention.Condition.ABSENT,
        )

        other_intervention.refresh_from_db()
        self.assertEqual(other_intervention.condition, SignalingIntervention.Condition.OK)
