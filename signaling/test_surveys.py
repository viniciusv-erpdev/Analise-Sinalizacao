from math import degrees

import pandas as pd
from django.test import TestCase
from django.urls import reverse

from accidents.normalizer import INDIVIDUAL_COUNT_COLUMNS
from analysis.spatial import EARTH_RADIUS_METERS, haversine_distance_meters
from signaling.models import SignalingIntervention, SignalingPoint
from signaling.surveys import (
    build_signaling_survey,
    ANALYSIS_SESSION_KEY,
)


class SignalingSurveyTests(TestCase):
    def setUp(self):
        self.point = SignalingPoint.objects.create(
            latitude=0,
            longitude=0,
            status=SignalingPoint.Status.INCOMPLETE,
        )

    def accident(
        self,
        accident_id: int,
        latitude: float = 0,
        longitude: float = 0,
        accident_type: str = "COLISAO",
        record_type: str = "SINISTRO NAO FATAL",
        **mode_counts: int,
    ) -> dict[str, object]:
        row = {
            "id": accident_id,
            "date": pd.Timestamp("2025-05-14"),
            "latitude": latitude,
            "longitude": longitude,
            "accident_type": accident_type,
            "record_type": record_type,
            "street": "RUA TESTE",
        }
        row.update({column: 0 for column in INDIVIDUAL_COUNT_COLUMNS})
        row.update(mode_counts)
        return row

    def survey(self, *accidents: dict[str, object]) -> dict[str, object]:
        return build_signaling_survey(self.point, pd.DataFrame(accidents))

    def test_accident_exactly_at_point_is_included(self):
        result = self.survey(self.accident(1))

        self.assertEqual(result["total_accidents"], 1)
        self.assertEqual(result["accidents"][0]["distance_meters"], 0)

    def test_accident_at_twenty_meters_is_included(self):
        latitude = degrees(20 / EARTH_RADIUS_METERS)

        result = self.survey(self.accident(1, latitude=latitude))

        self.assertEqual(result["total_accidents"], 1)

    def test_accident_at_forty_nine_point_nine_meters_is_included(self):
        latitude = degrees(49.9 / EARTH_RADIUS_METERS)

        result = self.survey(self.accident(1, latitude=latitude))

        self.assertEqual(result["total_accidents"], 1)

    def test_accident_exactly_at_fifty_meters_is_included(self):
        latitude = degrees(self.point.search_radius_meters / EARTH_RADIUS_METERS)
        distance = haversine_distance_meters(0, 0, latitude, 0)

        result = self.survey(self.accident(1, latitude=latitude))

        self.assertAlmostEqual(distance, self.point.search_radius_meters)
        self.assertEqual(result["total_accidents"], 1)

    def test_accident_outside_fifty_meters_is_excluded(self):
        latitude = degrees(50.01 / EARTH_RADIUS_METERS)

        result = self.survey(self.accident(1, latitude=latitude))

        self.assertEqual(result["total_accidents"], 0)
        self.assertEqual(result["accidents"], [])

    def test_two_nearby_accidents_are_independent(self):
        result = self.survey(self.accident(1), self.accident(2))

        self.assertEqual(result["total_accidents"], 2)
        self.assertEqual(
            [accident["id"] for accident in result["accidents"]],
            ["1", "2"],
        )

    def test_no_nearby_accident_returns_empty_result(self):
        result = self.survey()

        self.assertEqual(result["total_accidents"], 0)
        self.assertEqual(result["summary"]["fatal"], 0)
        self.assertEqual(result["summary"]["non_fatal"], 0)

    def test_summarizes_fatal_and_non_fatal_accidents(self):
        result = self.survey(
            self.accident(1, record_type="SINISTRO FATAL"),
            self.accident(2, record_type="SINISTRO NAO FATAL"),
            self.accident(3, record_type="SINISTRO NAO FATAL"),
        )

        self.assertEqual(result["summary"]["fatal"], 1)
        self.assertEqual(result["summary"]["non_fatal"], 2)

    def test_counts_each_accident_category(self):
        result = self.survey(
            self.accident(1, accident_type="ATROPELAMENTO"),
            self.accident(2, accident_type="CHOQUE"),
            self.accident(3, accident_type="COLISAO"),
            self.accident(4, accident_type="NAO_DISPONIVEL"),
            self.accident(5, accident_type="TIPO DESCONHECIDO"),
        )

        self.assertEqual(result["summary"]["by_type"], {
            "Atropelamento": 1,
            "Choque": 1,
            "Colisão": 1,
            "Não disponível": 1,
            "Outros": 1,
        })

    def test_includes_related_interventions(self):
        intervention = SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
        )

        result = self.survey()

        self.assertEqual(result["interventions"][0], {
            "id": intervention.id,
            "type": "TRAFFIC_LIGHT",
            "type_label": "Semáforo",
            "condition": "OK",
            "condition_label": "Adequada",
            "notes": "",
        })

    def test_preserves_intervention_notes(self):
        SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.SPEED_BUMP,
            condition=SignalingIntervention.Condition.ABSENT,
            notes="Pintura desgastada.",
        )

        result = self.survey()

        self.assertEqual(result["interventions"][0]["notes"], "Pintura desgastada.")
        self.assertEqual(result["interventions"][0]["condition_label"], "Inadequada")

    def test_point_without_interventions_has_empty_list(self):
        result = self.survey(self.accident(1, car_count=2))

        self.assertEqual(result["interventions"], [])
        self.assertEqual(result["status"], {
            "value": "INCOMPLETE",
            "label": "Incompleta",
        })
        self.assertEqual(result["accidents"][0]["modes"], [
            {"name": "Automóvel", "quantity": 2},
        ])


    def test_each_point_uses_its_persisted_search_radius(self):
        accident_at_forty = self.accident(
            1,
            latitude=degrees(40 / EARTH_RADIUS_METERS),
        )
        accident_at_eighty = self.accident(
            2,
            latitude=degrees(80 / EARTH_RADIUS_METERS),
        )

        self.point.search_radius_meters = 50
        self.point.save(update_fields=["search_radius_meters"])
        survey_at_fifty = self.survey(accident_at_forty, accident_at_eighty)

        self.point.search_radius_meters = 100
        self.point.save(update_fields=["search_radius_meters"])
        survey_at_one_hundred = self.survey(accident_at_forty, accident_at_eighty)

        self.assertEqual(survey_at_fifty["total_accidents"], 1)
        self.assertEqual(survey_at_fifty["radius_meters"], 50)
        self.assertEqual(survey_at_one_hundred["total_accidents"], 2)
        self.assertEqual(survey_at_one_hundred["radius_meters"], 100)

    def test_different_points_use_independent_search_radii(self):
        other_point = SignalingPoint.objects.create(
            latitude=0,
            longitude=0,
            status=SignalingPoint.Status.OK,
            search_radius_meters=150,
        )
        accident = self.accident(
            1,
            latitude=degrees(100 / EARTH_RADIUS_METERS),
        )

        first_survey = self.survey(accident)
        second_survey = build_signaling_survey(
            other_point,
            pd.DataFrame([accident]),
        )

        self.assertEqual(first_survey["total_accidents"], 0)
        self.assertEqual(second_survey["total_accidents"], 1)


class SignalingReportTests(TestCase):
    def accident_item(self, latitude: float = 0, longitude: float = 0):
        return {
            "id": "A-1",
            "latitude": latitude,
            "longitude": longitude,
            "record_type": "SINISTRO NAO FATAL",
            "date": "14/05/2025",
            "accident_type": "Colisão",
            "category": "collision",
            "street": "RUA TESTE",
            "modes": [{"name": "Automóvel", "quantity": 1}],
        }

    def set_individual_analysis(self, accidents):
        session = self.client.session
        session[ANALYSIS_SESSION_KEY] = {
            "view_mode": "individual",
            "map_data": accidents,
            "import_summary": {},
        }
        session.save()

    def create_point(self, latitude=0, longitude=0):
        return SignalingPoint.objects.create(
            latitude=latitude,
            longitude=longitude,
            status=SignalingPoint.Status.INCOMPLETE,
        )

    def test_existing_point_has_on_demand_report(self):
        point = self.create_point()
        self.set_individual_analysis([self.accident_item()])

        response = self.client.get(
            reverse("signaling:point-report", args=[point.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["survey"]["total_accidents"], 1)
        self.assertTrue(SignalingPoint.objects.filter(pk=point.id).exists())

        map_response = self.client.get(reverse("analysis"))
        self.assertEqual(
            map_response.context["signaling_map_data"][0]["id"],
            point.id,
        )

    def test_point_created_after_analysis_has_report_without_reload(self):
        self.set_individual_analysis([self.accident_item()])
        point = self.create_point()

        response = self.client.get(
            reverse("signaling:point-report", args=[point.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["survey"]["signaling_point_id"], point.id)
        self.assertEqual(response.context["survey"]["total_accidents"], 1)

    def test_report_with_no_nearby_accidents_returns_200(self):
        point = self.create_point(latitude=1, longitude=1)
        self.set_individual_analysis([self.accident_item()])

        response = self.client.get(
            reverse("signaling:point-report", args=[point.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["survey"]["total_accidents"], 0)
        self.assertContains(response, "Nenhum sinistro encontrado em um raio de 50 m")

    def test_report_includes_multiple_interventions_and_notes(self):
        point = self.create_point()
        SignalingIntervention.objects.create(
            signaling_point=point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
            notes="Sentido norte",
        )
        SignalingIntervention.objects.create(
            signaling_point=point,
            type=SignalingIntervention.Type.SPEED_BUMP,
            condition=SignalingIntervention.Condition.ABSENT,
            notes="Pintura desgastada",
        )
        self.set_individual_analysis([])

        response = self.client.get(
            reverse("signaling:point-report", args=[point.id])
        )

        self.assertEqual(len(response.context["survey"]["interventions"]), 2)
        self.assertContains(response, "Sentido norte")
        self.assertContains(response, "Pintura desgastada")

    def test_report_without_individual_analysis_is_friendly(self):
        point = self.create_point()

        response = self.client.get(
            reverse("signaling:point-report", args=[point.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["survey"])
        self.assertContains(
            response,
            "Não há uma análise de sinistros individuais disponível",
        )

    def test_missing_point_returns_404(self):
        self.set_individual_analysis([])

        response = self.client.get(
            reverse("signaling:point-report", args=[999])
        )

        self.assertEqual(response.status_code, 404)
