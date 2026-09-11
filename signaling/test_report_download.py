from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import is_zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from signaling.models import SignalingIntervention, SignalingPoint
from signaling.surveys import ANALYSIS_SESSION_KEY


DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document"
)


class SignalingReportDownloadTests(TestCase):
    def setUp(self):
        self.point = SignalingPoint.objects.create(
            latitude=0,
            longitude=0,
            status=SignalingPoint.Status.INCOMPLETE,
            search_radius_meters=100,
        )
        self.url = reverse("signaling:point-report", args=[self.point.id])

    def set_individual_analysis(self, accidents=None):
        session = self.client.session
        session[ANALYSIS_SESSION_KEY] = {
            "view_mode": "individual",
            "map_data": accidents or [],
            "import_summary": {},
        }
        session.save()

    def valid_form_data(self):
        return {
            "inspection_address": "Avenida Teste, 100",
            "occurrence_date": "2026-09-01",
            "inspection_date": "2026-09-11",
            "inspector_name": "Responsável Teste",
        }

    def png_upload(self, name="local.png"):
        image_buffer = BytesIO()
        Image.new("RGB", (80, 50), "blue").save(image_buffer, format="PNG")
        return SimpleUploadedFile(
            name,
            image_buffer.getvalue(),
            content_type="image/png",
        )

    def response_bytes(self, response):
        content = b"".join(response.streaming_content)
        response.close()
        return content

    def test_get_displays_form_and_automatic_survey_data(self):
        self.set_individual_analysis()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="inspection_address"')
        self.assertContains(response, 'name="occurrence_date"')
        self.assertContains(response, 'name="inspection_date"')
        self.assertContains(response, 'name="inspector_name"')
        self.assertContains(response, 'name="photos"')
        self.assertContains(response, 'name="study_reason"')
        self.assertContains(response, 'name="study_objective"')
        self.assertContains(response, "multiple")
        self.assertContains(response, "100 m")
        self.assertContains(response, "Incompleta")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_html_shows_chart_accidents_and_intervention_details(self):
        self.set_individual_analysis([{
            "id": "A-1",
            "latitude": 0,
            "longitude": 0,
            "record_type": "SINISTRO NAO FATAL",
            "date": "11/09/2026",
            "accident_type": "Colisão",
            "category": "collision",
            "street": "RUA TESTE",
            "modes": [{"name": "Automóvel", "quantity": 1}],
        }])
        SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
            notes="Boa visibilidade",
        )

        response = self.client.get(self.url)

        self.assertContains(response, "data:image/png;base64,")
        self.assertContains(response, "Sinistros relacionados")
        self.assertContains(response, "A-1")
        self.assertContains(response, "Semáforo")
        self.assertContains(response, "Status:")
        self.assertContains(response, "Adequada")
        self.assertContains(response, "Boa visibilidade")
        self.assertContains(response, "icons/signaling/traffic-light.svg")

    @patch("signaling.views.generate_signaling_report")
    def test_new_fields_are_validated_and_passed_to_generator(self, generator_mock):
        generator_mock.return_value = BytesIO(b"docx")
        self.set_individual_analysis()
        data = self.valid_form_data()
        data.update({
            "study_reason": "Motivo temporário",
            "study_objective": "Objetivo temporário",
        })

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        passed_form_data = generator_mock.call_args.args[2]
        self.assertEqual(passed_form_data["study_reason"], "Motivo temporário")
        self.assertEqual(passed_form_data["study_objective"], "Objetivo temporário")

    def test_valid_post_returns_docx_attachment(self):
        self.set_individual_analysis()

        response = self.client.post(self.url, self.valid_form_data())
        content = self.response_bytes(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], DOCX_CONTENT_TYPE)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn(f"relatorio_local_{self.point.id}_", response["Content-Disposition"])
        self.assertGreater(len(content), 0)
        self.assertTrue(is_zipfile(BytesIO(content)))

    def test_missing_required_fields_renders_form_errors(self):
        self.set_individual_analysis()

        response = self.client.post(self.url, {"occurrence_date": "2026-09-01"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"].split(";")[0], "text/html")
        self.assertFormError(response.context["form"], "inspection_address", "Este campo é obrigatório.")
        self.assertFormError(response.context["form"], "inspection_date", "Este campo é obrigatório.")
        self.assertFormError(response.context["form"], "inspector_name", "Este campo é obrigatório.")

    def test_valid_png_photo_generates_docx(self):
        self.set_individual_analysis()
        data = self.valid_form_data()
        data["photos"] = self.png_upload()

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], DOCX_CONTENT_TYPE)
        self.assertTrue(is_zipfile(BytesIO(self.response_bytes(response))))

    def test_invalid_photo_format_renders_form_error(self):
        self.set_individual_analysis()
        data = self.valid_form_data()
        data["photos"] = SimpleUploadedFile(
            "not-image.txt",
            b"invalid",
            content_type="text/plain",
        )

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "photos",
            "Envie somente fotos nos formatos JPEG ou PNG.",
        )

    def test_more_than_ten_photos_renders_form_error(self):
        self.set_individual_analysis()
        data = self.valid_form_data()
        data["photos"] = [self.png_upload(f"photo-{index}.png") for index in range(11)]

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "photos",
            "Envie no máximo 10 fotos.",
        )

    def test_post_without_individual_analysis_does_not_generate_docx(self):
        response = self.client.post(self.url, self.valid_form_data())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"].split(";")[0], "text/html")
        self.assertContains(
            response,
            "Não há uma análise de sinistros individuais disponível",
        )

    def test_valid_empty_analysis_generates_zero_accident_report(self):
        self.set_individual_analysis([])

        response = self.client.post(self.url, self.valid_form_data())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], DOCX_CONTENT_TYPE)
        self.assertTrue(is_zipfile(BytesIO(self.response_bytes(response))))

    def test_generation_does_not_persist_data_or_files(self):
        self.set_individual_analysis([])
        intervention = SignalingIntervention.objects.create(
            signaling_point=self.point,
            type=SignalingIntervention.Type.TRAFFIC_LIGHT,
            condition=SignalingIntervention.Condition.OK,
            notes="Original",
        )
        original_point = (
            self.point.status,
            self.point.search_radius_meters,
            self.point.updated_at,
        )
        original_counts = (
            SignalingPoint.objects.count(),
            SignalingIntervention.objects.count(),
        )

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            data = self.valid_form_data()
            data["photos"] = self.png_upload()
            response = self.client.post(self.url, data)
            self.response_bytes(response)
            self.assertEqual(list(Path(media_root).iterdir()), [])

        self.point.refresh_from_db()
        intervention.refresh_from_db()
        self.assertEqual(
            (SignalingPoint.objects.count(), SignalingIntervention.objects.count()),
            original_counts,
        )
        self.assertEqual(
            (
                self.point.status,
                self.point.search_radius_meters,
                self.point.updated_at,
            ),
            original_point,
        )
        self.assertEqual(intervention.notes, "Original")
