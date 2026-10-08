"""Run unchanged against either configured database, always in Django's test DB."""
from contextlib import redirect_stdout
from io import StringIO
import runpy

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core import serializers
from django.core.management import call_command
from django.test import TestCase

from signaling.models import SignalingPoint, SignalingIntervention, SignalingPointProblem, SignalingPointProblemSolution


class DatabaseFixtureCompatibilityTests(TestCase):
    def persistence_manifest(self):
        with redirect_stdout(StringIO()):
            result = runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts" / "validate_persistence.py"))
        return result["manifest"]

    def test_fixture_preserves_ids_relations_values_and_resets_sequences(self):
        point = SignalingPoint.objects.create(pk=4100, latitude="-21.170123", longitude="-47.810456", status="OK")
        intervention = SignalingIntervention.objects.create(pk=4200, signaling_point=point, type="TRAFFIC_LIGHT", condition="OK", notes="Atenção à travessia")
        problem = SignalingPointProblem.objects.create(pk=4300, signaling_point=point, problem_code="P1")
        solution = SignalingPointProblemSolution.objects.create(pk=4400, problem=problem, solution_code="P1A")
        records = [point, intervention, problem, solution]
        for record in records:
            record.refresh_from_db()
        manifest_before = self.persistence_manifest()
        expected = serializers.serialize("python", records)
        fixture = serializers.serialize("xml", records)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "transfer.xml"
            path.write_text(fixture, encoding="utf-8")
            # Remove only these generated records inside the isolated test database.
            point.delete()
            call_command("loaddata", str(path), verbosity=0)
        self.assertEqual(self.persistence_manifest(), manifest_before)
        restored = SignalingPoint.objects.get(pk=4100)
        self.assertEqual(restored.latitude, Decimal("-21.170123"))
        self.assertEqual(restored.longitude, Decimal("-47.810456"))
        self.assertEqual(restored.created_at, point.created_at)
        self.assertEqual(restored.interventions.get().notes, intervention.notes)
        self.assertEqual(restored.problems.get().solutions.get().pk, 4400)
        for model, original in zip((SignalingPoint, SignalingIntervention, SignalingPointProblem, SignalingPointProblemSolution), expected):
            self.assertEqual(serializers.serialize("python", [model.objects.get(pk=original["pk"])])[0], original)
        self.assertGreater(SignalingPoint.objects.create(latitude="1", longitude="1", status="OK").pk, 4100)
        self.assertGreater(SignalingIntervention.objects.create(signaling_point=restored, type="R1", condition="OK").pk, 4200)
        other = SignalingPointProblem.objects.create(signaling_point=restored, problem_code="P2")
        self.assertGreater(other.pk, 4300)
        self.assertGreater(SignalingPointProblemSolution.objects.create(problem=other, solution_code="P2A").pk, 4400)
