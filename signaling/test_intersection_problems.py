"""Contrato persistente dos problemas: catálogo, ORM e API, sem interface."""
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse

from signaling.intersection_problems import (
    get_problem, get_problem_solutions, is_valid_problem_solution,
    serialize_problem_catalog, validate_problem_solution, validate_problem_solutions,
)
from signaling.models import SignalingIntervention, SignalingPoint, SignalingPointProblem, SignalingPointProblemSolution
from signaling.services import create_point_problem, get_signaling_map_data, serialize_point_problem, update_point_problem_solutions
from signaling.surveys import ANALYSIS_SESSION_KEY


# Independent expected API fixture: official texts and stable identifiers.
EXPECTED_CATALOG = json.loads(r'''[
  {
    "code": "P1",
    "text": "O condutor não enxerga as brechas e transpõe a intersecção em condições impróprias.",
    "solutions": [
      {
        "code": "P1A",
        "text": "Remoção de interferências visuais."
      },
      {
        "code": "P1B",
        "text": "Avanço do alinhamento da via perpendicular por meio de construção de avanço de calçada e implantação de linha de retenção ou de continuidade do alinhamento."
      }
    ]
  },
  {
    "code": "P2",
    "text": "Não há brechas para transposição.",
    "solutions": [
      {
        "code": "P2A",
        "text": "Implantação de rotatória ou mini rotatória."
      },
      {
        "code": "P2B",
        "text": "Implantação de sinalização semafórica."
      }
    ]
  },
  {
    "code": "P3",
    "text": "As velocidades de aproximação são elevadas ou há dificuldade para avaliar a velocidade de aproximação de veículos da transversal.",
    "solutions": [
      {
        "code": "P3A",
        "text": "Implantação de sinalização de regulamentação de velocidade."
      },
      {
        "code": "P3B",
        "text": "Implantação de fiscalização de velocidade."
      },
      {
        "code": "P3C",
        "text": "Implantação de redutores de velocidade."
      },
      {
        "code": "P3D",
        "text": "Implantação de sinalização semafórica."
      }
    ]
  },
  {
    "code": "P4",
    "text": "As normas de preferência de passagem não são respeitadas.",
    "solutions": [
      {
        "code": "P4A",
        "text": "Definição da preferencial por meio de sinal R-1 – Parada Obrigatória ou R-2 – Dê a Preferência."
      },
      {
        "code": "P4B",
        "text": "Redefinição da via preferencial – inversão da sinalização de preferência de passagem."
      },
      {
        "code": "P4C",
        "text": "Implantação de sinalização semafórica de advertência."
      },
      {
        "code": "P4D",
        "text": "Implantação de rotatória ou mini rotatória."
      },
      {
        "code": "P4E",
        "text": "Implantação de sinalização semafórica de regulamentação."
      }
    ]
  },
  {
    "code": "P5",
    "text": "Muitos movimentos conflitantes.",
    "solutions": [
      {
        "code": "P5A",
        "text": "Proibição de movimentos por meio de sinalização."
      },
      {
        "code": "P5B",
        "text": "Implantação de rotatória ou mini rotatória."
      },
      {
        "code": "P5C",
        "text": "Alteração de circulação."
      },
      {
        "code": "P5D",
        "text": "Implantação de sinalização semafórica (pares de vias com mão única de circulação, em sentidos opostos)."
      }
    ]
  }
]''')
VALID_PAIRS = [
    (problem["code"], solution["code"])
    for problem in EXPECTED_CATALOG for solution in problem["solutions"]
]
INVALID_PAIRS = [
    ("P1", "P3A"), ("P2", "P4A"), ("P3", "P1A"), ("P4", "P5A"), ("P5", "P2A"),
    ("P9", "P1A"), ("P1", "P9A"), ("", "P1A"), ("P1", ""),
    (None, "P1A"), ("P1", None), (1, "P1A"), ("P1", 1),
    ([], "P1A"), ("P1", {}), (True, "P1A"), ("P1", False),
]


def make_point():
    return SignalingPoint.objects.create(
        latitude="-21.170000", longitude="-47.810000", status="INCOMPLETE",
    )


class ProblemCatalogTests(SimpleTestCase):
    def test_exact_catalog_codes_texts_and_solution_membership(self):
        self.assertEqual(serialize_problem_catalog(), EXPECTED_CATALOG)
        self.assertEqual([p["code"] for p in EXPECTED_CATALOG], ["P1", "P2", "P3", "P4", "P5"])
        self.assertEqual(
            [[s["code"] for s in p["solutions"]] for p in EXPECTED_CATALOG],
            [["P1A", "P1B"], ["P2A", "P2B"], ["P3A", "P3B", "P3C", "P3D"],
             ["P4A", "P4B", "P4C", "P4D", "P4E"], ["P5A", "P5B", "P5C", "P5D"]],
        )

    def test_valid_pairs_and_helpers(self):
        for problem, solution in VALID_PAIRS:
            with self.subTest(problem=problem, solution=solution):
                self.assertEqual(get_problem(problem).code, problem)
                self.assertIn(solution, dict(get_problem_solutions(problem)))
                self.assertTrue(is_valid_problem_solution(problem, solution))
                validate_problem_solution(problem, solution)

    def test_invalid_codes_types_and_relationships(self):
        for problem, solution in INVALID_PAIRS:
            with self.subTest(problem=problem, solution=solution):
                self.assertFalse(is_valid_problem_solution(problem, solution))
                with self.assertRaises(ValidationError):
                    validate_problem_solution(problem, solution)
        self.assertIsNone(get_problem("unknown"))
        self.assertEqual(get_problem_solutions("unknown"), ())

    def test_serialized_catalog_cannot_mutate_source(self):
        catalog = serialize_problem_catalog()
        catalog[0]["solutions"][0]["text"] = "alterado"
        self.assertEqual(serialize_problem_catalog(), EXPECTED_CATALOG)


class PointProblemTests(TestCase):
    def setUp(self):
        self.point = make_point()

    def test_subsets_full_sets_and_separate_waypoints(self):
        for code, codes in [
            ("P1", ["P1A", "P1B"]),
            ("P3", ["P3A", "P3B", "P3C", "P3D"]),
            ("P4", ["P4A", "P4B", "P4C", "P4D", "P4E"]),
        ]:
            record = create_point_problem(self.point, code, codes)
            self.assertEqual(list(record.solutions.values_list("solution_code", flat=True)), codes)
        create_point_problem(make_point(), "P1", ["P1A"])
        self.assertEqual(self.point.problems.count(), 3)

    def test_database_uniqueness_for_problem_and_solution(self):
        record = create_point_problem(self.point, "P1", ["P1A"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            SignalingPointProblem.objects.create(signaling_point=self.point, problem_code="P1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            SignalingPointProblemSolution.objects.create(problem=record, solution_code="P1A")

    def test_model_validation_and_database_domains(self):
        record = create_point_problem(self.point, "P1", ["P1A"])
        with self.assertRaises(ValidationError):
            SignalingPointProblemSolution(problem=record, solution_code="P3A").full_clean()
        for code in ["", None, "P9"]:
            with self.subTest(code=code), self.assertRaises(IntegrityError), transaction.atomic():
                SignalingPointProblem.objects.create(signaling_point=self.point, problem_code=code)
        for code in ["", None, "P9A"]:
            with self.subTest(code=code), self.assertRaises(IntegrityError), transaction.atomic():
                SignalingPointProblemSolution.objects.create(problem=record, solution_code=code)

    def test_cascades_do_not_touch_other_problems(self):
        first = create_point_problem(self.point, "P1", ["P1A", "P1B"])
        second = create_point_problem(self.point, "P3", ["P3C"])
        first.delete()
        self.assertEqual(SignalingPointProblemSolution.objects.get().problem_id, second.pk)
        self.point.delete()
        self.assertFalse(SignalingPointProblem.objects.exists())
        self.assertFalse(SignalingPointProblemSolution.objects.exists())

    def test_catalog_order_and_codes_only(self):
        record = create_point_problem(self.point, "P1", ["P1B", "P1A"])
        self.assertEqual(str(record), f"Ponto {self.point.pk}: P1")
        self.assertEqual(serialize_point_problem(record), {
            "id": record.pk, "problem_code": "P1", "problem_text": EXPECTED_CATALOG[0]["text"],
            "solutions": EXPECTED_CATALOG[0]["solutions"],
        })
        self.assertEqual({f.name for f in record._meta.fields},
            {"id", "signaling_point", "problem_code", "created_at", "updated_at"})
        self.assertEqual({f.name for f in SignalingPointProblemSolution._meta.fields},
            {"id", "problem", "solution_code", "created_at"})

    def test_invalid_sets_never_create_partial_problem(self):
        for codes in [[], None, "P1A", 1, {}, ["P3A"], ["P1A", "P3A"],
                      ["P1A", "P1A"], ["P9A"], [None], [[]], [True]]:
            with self.subTest(codes=codes), self.assertRaises(ValidationError):
                create_point_problem(self.point, "P1", codes)
        self.assertFalse(SignalingPointProblem.objects.exists())

    def test_write_failure_rolls_back_creation_and_replacement(self):
        original = SignalingPointProblemSolution.objects.bulk_create
        def fail_after_insert(rows):
            original(rows[:1])
            raise IntegrityError("simulated failure")
        with patch("signaling.services.SignalingPointProblemSolution.objects.bulk_create",
                   side_effect=fail_after_insert):
            with self.assertRaises(IntegrityError):
                create_point_problem(self.point, "P1", ["P1A", "P1B"])
        self.assertFalse(SignalingPointProblem.objects.exists())
        record = create_point_problem(self.point, "P3", ["P3A", "P3B"])
        before = record.updated_at
        with patch("signaling.services.SignalingPointProblemSolution.objects.bulk_create",
                   side_effect=fail_after_insert):
            with self.assertRaises(IntegrityError):
                update_point_problem_solutions(record, ["P3C", "P3D"])
        record.refresh_from_db()
        self.assertEqual(record.updated_at, before)
        self.assertEqual(list(record.solutions.values_list("solution_code", flat=True)), ["P3A", "P3B"])


class PointProblemAPITests(TestCase):
    def setUp(self):
        self.point = make_point()
        self.url = reverse("signaling:point-problems", args=[self.point.pk])

    def post(self, payload, url=None, client=None):
        return (client or self.client).post(
            url or self.url, data=json.dumps(payload), content_type="application/json",
        )

    def create(self, code="P1", solution="P1A"):
        response = self.post({"problem_code": code, "solution_codes": [solution]})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def record_url(self, action, record, point=None):
        return reverse(
            "signaling:" + action, args=[(point or self.point).pk, record["id"]],
        )

    def test_post_p1_two_solutions_persists_orm_and_get_returns_grouped_texts(self):
        response = self.post({"problem_code": "P1", "solution_codes": ["P1A", "P1B"]})
        self.assertEqual(response.status_code, 201)
        problem = self.point.problems.get()
        self.assertEqual(problem.problem_code, "P1")
        self.assertEqual(list(problem.solutions.values_list("solution_code", flat=True)), ["P1A", "P1B"])
        result = Client().get(self.url)
        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertEqual(data["point_id"], self.point.pk)
        self.assertEqual(data["problems"], [{
            "id": problem.pk, "problem_code": "P1",
            "problem_text": EXPECTED_CATALOG[0]["text"],
            "solutions": EXPECTED_CATALOG[0]["solutions"],
        }])

    def test_multiple_solution_creation_and_replacement(self):
        response = self.post({"problem_code": "P3", "solution_codes": ["P3B", "P3A"]})
        self.assertEqual(response.status_code, 201)
        record = response.json()
        self.assertEqual([item["code"] for item in record["solutions"]], ["P3A", "P3B"])
        url = self.record_url("update-problem-solution", record)
        for codes in [["P3A", "P3B", "P3C"], ["P3B"], ["P3C", "P3D"]]:
            result = self.post({"solution_codes": codes}, url)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["id"], record["id"])
            self.assertEqual([item["code"] for item in result.json()["solutions"]], codes)
            self.assertEqual(Client().get(self.url).json()["problems"][0]["solutions"],
                             result.json()["solutions"])
        confirmed = Client().get(self.url).json()["problems"]
        for codes in [[], None, "P3A", ["P3C", "P1A"], ["P3C", "P3C"], [None]]:
            self.assertEqual(self.post({"solution_codes": codes}, url).status_code, 400)
            self.assertEqual(Client().get(self.url).json()["problems"], confirmed)

    def test_multiple_creation_and_invalid_collection_payloads(self):
        for code, codes in [("P1", ["P1A", "P1B"]),
                           ("P4", ["P4A", "P4B", "P4C", "P4D", "P4E"])]:
            response = self.post({"problem_code": code, "solution_codes": codes})
            self.assertEqual(response.status_code, 201)
            self.assertEqual([x["code"] for x in response.json()["solutions"]], codes)
        self.assertEqual(SignalingPointProblemSolution.objects.count(), 7)
        self.assertEqual(self.post({"problem_code": "P1", "solution_codes": ["P1A"]}).status_code, 400)
        for codes in [[], None, "P2A", {}, ["P2A", "P3A"], ["P2A", "P2A"], [False]]:
            self.assertEqual(self.post({"problem_code": "P2", "solution_codes": codes}).status_code, 400)
        self.assertFalse(self.point.problems.filter(problem_code="P2").exists())

    def test_old_singular_contract_is_rejected(self):
        self.assertEqual(self.post({"problem_code": "P1", "solution_code": "P1A"}).status_code, 400)
        record = self.create()
        self.assertEqual(self.post({"solution_code": "P1B"},
                         self.record_url("update-problem-solution", record)).status_code, 400)

    def test_empty_get_is_read_only_and_returns_catalog(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "success": True, "point_id": self.point.pk,
            "catalog": EXPECTED_CATALOG, "problems": [],
        })
        self.assertFalse(SignalingPointProblem.objects.exists())

    def test_create_multiple_and_persist_in_new_client_session(self):
        first = self.create()
        self.create("P3", "P3C")
        response = Client().get(self.url)
        self.assertEqual(response.status_code, 200)
        records = response.json()["problems"]
        self.assertEqual([p["problem_code"] for p in records], ["P1", "P3"])
        self.assertEqual(records[0], {k: v for k, v in first.items() if k != "success"})

    def test_duplicate_does_not_replace_existing_solution(self):
        self.create()
        for solution in ["P1A", "P1B"]:
            response = self.post({"problem_code": "P1", "solution_codes": [solution]})
            self.assertEqual(response.status_code, 400)
            self.assertIn("já está cadastrado", response.json()["errors"]["problem_code"][0])
        self.assertEqual(self.point.problems.count(), 1)
        self.assertEqual(self.point.problems.get().solutions.get().solution_code, "P1A")

    def test_all_valid_pairs(self):
        for code, solution in VALID_PAIRS:
            with self.subTest(code=code, solution=solution):
                record = self.create(code, solution)
                self.assertEqual(record["solutions"][0]["code"], solution)
                self.point.problems.all().delete()

    def test_all_invalid_pairs_and_types_leave_database_unchanged(self):
        for code, solution in INVALID_PAIRS:
            with self.subTest(code=code, solution=solution):
                response = self.post({"problem_code": code, "solution_codes": [solution]})
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["success"])
        self.assertFalse(SignalingPointProblem.objects.exists())

    def test_missing_codes_and_malformed_json(self):
        for data in [{}, {"problem_code": "P1"}, {"solution_codes": ["P1A"]}, [], None, "text"]:
            self.assertEqual(self.post(data).status_code, 400)
        for body in ["{", b"\xff"]:
            response = self.client.post(self.url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
        self.assertFalse(SignalingPointProblem.objects.exists())

    def test_browser_text_is_not_trusted(self):
        response = self.post({
            "problem_code": "P1", "solution_codes": ["P1A"],
            "problem_text": "forjado", "solution_text": "forjado",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["problem_text"], EXPECTED_CATALOG[0]["text"])
        self.assertEqual(response.json()["solutions"][0]["text"], EXPECTED_CATALOG[0]["solutions"][0]["text"])

    def test_missing_waypoint(self):
        url = reverse("signaling:point-problems", args=[99999])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.post({"problem_code": "P1", "solution_codes": ["P1A"]}, url).status_code, 404)

    def test_explicit_solution_update_preserves_record_and_problem(self):
        record = self.create()
        original = self.point.problems.get()
        url = self.record_url("update-problem-solution", record)
        response = self.post({"solution_codes": ["P1B"]}, url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], original.pk)
        original.refresh_from_db()
        self.assertEqual(original.problem_code, "P1")
        self.assertEqual(original.solutions.get().solution_code, "P1B")
        self.assertEqual(self.point.problems.count(), 1)
        self.assertGreaterEqual(original.updated_at, original.created_at)
        self.assertEqual(Client().get(self.url).json()["problems"][0]["solutions"][0]["code"], "P1B")

    def test_invalid_update_never_changes_persisted_pair(self):
        record = self.create()
        url = self.record_url("update-problem-solution", record)
        for payload in [
            {"solution_codes": ["P3A"]}, {"solution_codes": None}, {"solution_codes": []},
            {"solution_codes": [""]}, {"solution_codes": ["P9A"]}, {},
            {"problem_code": "P2", "solution_codes": ["P2A"]}, [],
        ]:
            self.assertEqual(self.post(payload, url).status_code, 400)
        self.assertEqual(self.client.post(url, data="{", content_type="application/json").status_code, 400)
        self.assertEqual(self.point.problems.get().solutions.get().solution_code, "P1A")

    def test_delete_only_target_and_repeat_returns_404(self):
        record = self.create()
        self.create("P3", "P3C")
        url = self.record_url("delete-point-problem", record)
        self.assertEqual(self.post({}, url).status_code, 200)
        self.assertEqual(list(self.point.problems.values_list("problem_code", flat=True)), ["P3"])
        self.assertEqual(self.post({}, url).status_code, 404)
        self.assertTrue(SignalingPoint.objects.filter(pk=self.point.pk).exists())

    def test_update_and_delete_are_scoped_to_waypoint(self):
        record = self.create()
        other = make_point()
        for action in ["update-problem-solution", "delete-point-problem"]:
            response = self.post({"solution_codes": ["P1B"]}, self.record_url(action, record, other))
            self.assertEqual(response.status_code, 404)
            missing = self.record_url(action, {"id": 99999})
            self.assertEqual(self.post({"solution_codes": ["P1B"]}, missing).status_code, 404)
        self.assertEqual(self.point.problems.get().solutions.get().solution_code, "P1A")

    def test_method_restrictions(self):
        record = self.create()
        for action in ["update-problem-solution", "delete-point-problem"]:
            self.assertEqual(self.client.get(self.record_url(action, record)).status_code, 405)
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.assertEqual(self.client.put(self.url).status_code, 405)

    def test_shared_access_and_csrf_protection_for_all_writes(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(self.url).status_code, 200)
        payload = {"problem_code": "P1", "solution_codes": ["P1A"]}
        self.assertEqual(self.post(payload, client=client).status_code, 403)
        client.get(reverse("analysis"))
        token = client.cookies["csrftoken"].value
        response = client.post(self.url, data=json.dumps(payload),
            content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)
        for action, body in [
            ("update-problem-solution", {"solution_codes": ["P1B"]}),
            ("delete-point-problem", {}),
        ]:
            url = self.record_url(action, response.json())
            self.assertEqual(self.post(body, url, client).status_code, 403)
            self.assertEqual(client.post(url, data=json.dumps(body),
                content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_existing_waypoint_delete_cascades(self):
        self.create()
        response = self.post({}, reverse("signaling:delete-point", args=[self.point.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SignalingPointProblem.objects.exists())

    def test_problem_operations_preserve_point_interventions_map_and_session(self):
        intervention = SignalingIntervention.objects.create(
            signaling_point=self.point, type="TRAFFIC_LIGHT", condition="OK", notes="Existente",
        )
        point_before = SignalingPoint.objects.values().get(pk=self.point.pk)
        intervention_before = SignalingIntervention.objects.values().get(pk=intervention.pk)
        session = self.client.session
        session[ANALYSIS_SESSION_KEY] = {"view_mode": "individual", "map_data": [], "analysis_id": "test"}
        session.save()
        session_before = dict(self.client.session)
        map_before = get_signaling_map_data()
        record = self.create()
        self.post({"solution_codes": ["P1B"]}, self.record_url("update-problem-solution", record))
        self.post({}, self.record_url("delete-point-problem", record))
        self.assertEqual(SignalingPoint.objects.values().get(pk=self.point.pk), point_before)
        self.assertEqual(SignalingIntervention.objects.values().get(pk=intervention.pk), intervention_before)
        self.assertEqual(get_signaling_map_data(), map_before)
        self.assertEqual(dict(self.client.session), session_before)


class ProblemMigrationTests(TransactionTestCase):
    def test_migration_preserves_existing_points_and_interventions(self):
        executor = MigrationExecutor(connection)
        before = ("signaling", "0005_signalingpoint_search_radius_meters")
        after = ("signaling", "0006_signalingpointproblem")
        try:
            executor.migrate([before])
            apps = executor.loader.project_state([before]).apps
            point = apps.get_model("signaling", "SignalingPoint").objects.create(
                latitude="-21.17", longitude="-47.81", status="OK", search_radius_meters=80,
            )
            intervention = apps.get_model("signaling", "SignalingIntervention").objects.create(
                signaling_point=point, type="TRAFFIC_LIGHT", condition="OK", notes="Preservar",
            )
            executor = MigrationExecutor(connection)
            executor.migrate([after])
            apps = executor.loader.project_state([after]).apps
            self.assertEqual(apps.get_model("signaling", "SignalingPoint").objects.get(pk=point.pk).search_radius_meters, 80)
            self.assertEqual(apps.get_model("signaling", "SignalingIntervention").objects.get(pk=intervention.pk).notes, "Preservar")
            problems = apps.get_model("signaling", "SignalingPointProblem")
            self.assertEqual(problems.objects.count(), 0)
            problems.objects.create(signaling_point_id=point.pk, problem_code="P1", solution_code="P1A")
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())


class MultipleSolutionsMigrationTests(TransactionTestCase):
    def test_existing_codes_ids_timestamps_preserved_and_lossy_reverse_refused(self):
        from django.db.migrations.exceptions import IrreversibleError
        before = ("signaling", "0006_signalingpointproblem")
        after = ("signaling", "0007_multiple_problem_solutions")
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([before])
            apps = executor.loader.project_state([before]).apps
            point = apps.get_model("signaling", "SignalingPoint").objects.create(
                latitude="-21.17", longitude="-47.81", status="OK", search_radius_meters=80,
            )
            old = apps.get_model("signaling", "SignalingPointProblem").objects.create(
                signaling_point_id=point.pk, problem_code="P1", solution_code="P1B",
            )
            executor = MigrationExecutor(connection)
            executor.migrate([after])
            apps = executor.loader.project_state([after]).apps
            record = apps.get_model("signaling", "SignalingPointProblem").objects.get(pk=old.pk)
            Solution = apps.get_model("signaling", "SignalingPointProblemSolution")
            self.assertEqual(record.created_at, old.created_at)
            self.assertEqual(record.updated_at, old.updated_at)
            self.assertEqual(record.signaling_point_id, point.pk)
            self.assertEqual(Solution.objects.get(problem_id=old.pk).solution_code, "P1B")
            # A safe single-solution reversal also restores the old field.
            executor = MigrationExecutor(connection)
            executor.migrate([before])
            restored = executor.loader.project_state([before]).apps.get_model(
                "signaling", "SignalingPointProblem",
            ).objects.get(pk=old.pk)
            self.assertEqual(restored.solution_code, "P1B")
            executor = MigrationExecutor(connection)
            executor.migrate([after])
            Solution.objects.create(problem_id=old.pk, solution_code="P1A")
            with self.assertRaises(IrreversibleError):
                MigrationExecutor(connection).migrate([before])
            self.assertEqual(Solution.objects.filter(problem_id=old.pk).count(), 2)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
