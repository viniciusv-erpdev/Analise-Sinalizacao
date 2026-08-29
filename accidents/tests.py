from unittest.mock import patch

import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from accidents.services import (
    AccidentImportError,
    import_accident_files,
)
from analysis.pipeline import (
    process_accidents,
)


SOURCE_COLUMNS = [
    "id_sinistro",
    "data_sinistro",
    "latitude",
    "longitude",
    "tp_sinistro_primario",
    "logradouro",
    "numero_logradouro",
    "municipio",
]


def make_csv(
    rows: list[list[object]],
    encoding: str = "utf-8",
) -> bytes:
    header = ";".join(SOURCE_COLUMNS)
    lines = [
        ";".join(str(value) for value in row)
        for row in rows
    ]
    return "\n".join([header, *lines]).encode(encoding)


def make_upload(
    name: str,
    rows: list[list[object]],
    encoding: str = "utf-8",
) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name,
        make_csv(rows, encoding),
        content_type="text/csv",
    )


class AccidentImportTests(SimpleTestCase):
    def test_reads_valid_utf8_csv(self):
        uploaded_file = make_upload(
            "utf8.csv",
            [[1, "31/07/2026", "-21,17", "-47,81", "COLISAO", "AVENIDA SÃO JOÃO", 10, "RIBEIRAO PRETO"]],
        )

        result = import_accident_files([uploaded_file])

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["logradouro"], "AVENIDA SÃO JOÃO")

    def test_consolidates_two_files(self):
        first = make_upload(
            "first.csv",
            [[1, "31/07/2026", -21.17, -47.81, "COLISAO", "RUA A", 10, "RIBEIRAO PRETO"]],
        )
        second = make_upload(
            "second.csv",
            [[2, "31/07/2026", -21.18, -47.82, "ATROPELAMENTO", "RUA B", 20, "RIBEIRAO PRETO"]],
        )

        result = import_accident_files([first, second])

        self.assertEqual(result["id_sinistro"].tolist(), [1, 2])

    def test_removes_duplicate_id_and_keeps_first_record(self):
        first = make_upload(
            "first.csv",
            [[1, "31/07/2026", -21.17, -47.81, "COLISAO", "PRIMEIRA RUA", 10, "RIBEIRAO PRETO"]],
        )
        second = make_upload(
            "second.csv",
            [[1, "31/07/2026", -21.18, -47.82, "COLISAO", "SEGUNDA RUA", 20, "RIBEIRAO PRETO"]],
        )

        result = import_accident_files([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["logradouro"], "PRIMEIRA RUA")

    def test_rejects_file_without_id_column(self):
        content = b"data_sinistro;latitude\n31/07/2026;-21.17"
        uploaded_file = SimpleUploadedFile("missing-id.csv", content)

        with self.assertRaisesRegex(
            AccidentImportError,
            "id_sinistro",
        ):
            import_accident_files([uploaded_file])

    def test_rejects_empty_file(self):
        uploaded_file = SimpleUploadedFile("empty.csv", b"")

        with self.assertRaisesRegex(
            AccidentImportError,
            "está vazio",
        ):
            import_accident_files([uploaded_file])

    def test_reads_latin1_csv_as_fallback(self):
        uploaded_file = make_upload(
            "latin1.csv",
            [[1, "31/07/2026", -21.17, -47.81, "COLISAO", "AVENIDA SÃO JOÃO", 10, "RIBEIRAO PRETO"]],
            encoding="latin-1",
        )

        result = import_accident_files([uploaded_file])

        self.assertEqual(result.iloc[0]["logradouro"], "AVENIDA SÃO JOÃO")

    def test_requires_at_least_one_file(self):
        with self.assertRaisesRegex(
            AccidentImportError,
            "pelo menos um arquivo",
        ):
            import_accident_files([])


class PipelineTests(SimpleTestCase):
    def test_process_accidents_accepts_dataframe(self):
        rows = [
            [index, "31/07/2026", -21.1775, -47.8103, "COLISAO", "RUA A", 10, "RIBEIRAO PRETO"]
            for index in range(1, 4)
        ]
        dataframe = pd.DataFrame(
            rows,
            columns=SOURCE_COLUMNS,
        )

        result = process_accidents(dataframe)

        self.assertEqual(len(result), 1)
        self.assertTrue(result.iloc[0]["eligible"])
        self.assertEqual(result.iloc[0]["collisions_1y"], 3)

class AnalysisViewTests(SimpleTestCase):
    map_data = [
        {
            "cluster_id": 7,
            "latitude": -21.17,
            "longitude": -47.81,
        }
    ]

    @patch("accidents.views.process_accidents")
    def test_get_shows_empty_map_and_upload_form(
        self,
        process_accidents_mock,
    ):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        process_accidents_mock.assert_not_called()
        self.assertEqual(response.context["results"], [])
        self.assertEqual(response.context["map_data"], [])
        self.assertContains(response, 'name="files"')
        self.assertContains(response, "multiple")
        self.assertContains(response, 'id="selected-files"')
        self.assertContains(response, 'id="analyze-button"')
        self.assertContains(response, "disabled")

    @patch("accidents.views.build_map_data")
    @patch("accidents.views.process_accidents")
    def test_post_with_valid_csv_processes_uploaded_data(
        self,
        process_accidents_mock,
        build_map_data_mock,
    ):
        results = pd.DataFrame({"eligible": [True]})
        process_accidents_mock.return_value = results
        build_map_data_mock.return_value = self.map_data
        uploaded_file = make_upload(
            "valid.csv",
            [[1, "31/07/2026", -21.17, -47.81, "COLISAO", "RUA A", 10, "RIBEIRAO PRETO"]],
        )

        response = self.client.post(
            "/",
            {"files": uploaded_file},
        )

        self.assertEqual(response.status_code, 200)
        consolidated = process_accidents_mock.call_args.args[0]
        self.assertEqual(len(consolidated), 1)
        self.assertEqual(response.context["map_data"], self.map_data)
        self.assertEqual(
            response.context["import_summary"],
            {
                "file_count": 1,
                "accident_count": 1,
                "eligible_count": 1,
            },
        )

    @patch("accidents.views.build_map_data", return_value=[])
    @patch("accidents.views.process_accidents", return_value=pd.DataFrame())
    def test_post_consolidates_two_csv_files(
        self,
        process_accidents_mock,
        _build_map_data_mock,
    ):
        first = make_upload(
            "first.csv",
            [[1, "31/07/2026", -21.17, -47.81, "COLISAO", "RUA A", 10, "RIBEIRAO PRETO"]],
        )
        second = make_upload(
            "second.csv",
            [[2, "31/07/2026", -21.18, -47.82, "COLISAO", "RUA B", 20, "RIBEIRAO PRETO"]],
        )

        response = self.client.post(
            "/",
            {"files": [first, second]},
        )

        consolidated = process_accidents_mock.call_args.args[0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            consolidated["id_sinistro"].tolist(),
            [1, 2],
        )
        self.assertEqual(
            response.context["import_summary"]["file_count"],
            2,
        )

    @patch("accidents.views.build_map_data", return_value=[])
    @patch("accidents.views.process_accidents", return_value=pd.DataFrame())
    def test_post_deduplicates_ids_before_processing(
        self,
        process_accidents_mock,
        _build_map_data_mock,
    ):
        first = make_upload(
            "first.csv",
            [[1, "31/07/2026", -21.17, -47.81, "COLISAO", "PRIMEIRA RUA", 10, "RIBEIRAO PRETO"]],
        )
        second = make_upload(
            "second.csv",
            [[1, "31/07/2026", -21.18, -47.82, "COLISAO", "SEGUNDA RUA", 20, "RIBEIRAO PRETO"]],
        )

        response = self.client.post(
            "/",
            {"files": [first, second]},
        )

        consolidated = process_accidents_mock.call_args.args[0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(consolidated), 1)
        self.assertEqual(
            consolidated.iloc[0]["logradouro"],
            "PRIMEIRA RUA",
        )

    @patch("accidents.views.process_accidents")
    def test_post_without_file_shows_error_and_empty_map(
        self,
        process_accidents_mock,
    ):
        response = self.client.post("/", {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione pelo menos um arquivo")
        process_accidents_mock.assert_not_called()
        self.assertEqual(response.context["map_data"], [])

    @patch("accidents.views.process_accidents")
    def test_post_with_empty_file_shows_error(
        self,
        process_accidents_mock,
    ):
        uploaded_file = SimpleUploadedFile("empty.csv", b"")

        response = self.client.post(
            "/",
            {"files": uploaded_file},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "está vazio")
        process_accidents_mock.assert_not_called()
        self.assertEqual(response.context["map_data"], [])

    @patch("accidents.views.process_accidents")
    def test_post_without_required_column_shows_error(
        self,
        process_accidents_mock,
    ):
        uploaded_file = SimpleUploadedFile(
            "missing-id.csv",
            b"data_sinistro;latitude\n31/07/2026;-21.17",
        )

        response = self.client.post(
            "/",
            {"files": uploaded_file},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "id_sinistro")
        process_accidents_mock.assert_not_called()
        self.assertEqual(response.context["map_data"], [])
