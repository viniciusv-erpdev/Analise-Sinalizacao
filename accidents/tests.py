from unittest.mock import patch

import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from accidents.services import (
    AccidentImportError,
    import_accident_files,
)
from analysis.criteria import (
    evaluate_criteria,
    evaluate_historical_criteria,
)
from analysis.map_data import build_map_data
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


class MapFilterDataTests(SimpleTestCase):
    def test_criteria_exposes_each_filter_condition(self):
        one_year = pd.DataFrame(
            [
                {
                    "cluster_id": 1,
                    "accident_count": 5,
                    "collisions": 3,
                    "pedestrians": 2,
                },
                {
                    "cluster_id": 2,
                    "accident_count": 1,
                    "collisions": 0,
                    "pedestrians": 0,
                },
            ]
        )
        three_years = pd.DataFrame(
            [
                {
                    "cluster_id": 1,
                    "accident_count": 6,
                    "collisions": 6,
                    "pedestrians": 3,
                },
                {
                    "cluster_id": 2,
                    "accident_count": 11,
                    "collisions": 7,
                    "pedestrians": 4,
                },
            ]
        )

        result = evaluate_criteria(one_year, three_years)
        cluster_1 = result[result["cluster_id"] == 1].iloc[0]
        cluster_2 = result[result["cluster_id"] == 2].iloc[0]

        self.assertTrue(cluster_1["collision_1y_met"])
        self.assertFalse(cluster_1["collision_3y_met"])
        self.assertTrue(cluster_1["pedestrian_1y_met"])
        self.assertFalse(cluster_1["pedestrian_3y_met"])
        self.assertFalse(cluster_2["collision_1y_met"])
        self.assertTrue(cluster_2["collision_3y_met"])
        self.assertFalse(cluster_2["pedestrian_1y_met"])
        self.assertTrue(cluster_2["pedestrian_3y_met"])

    def test_map_data_contains_boolean_filter_flags(self):
        rows = [
            [index, "31/07/2026", -21.1775, -47.8103, "COLISAO", "RUA A", 10, "RIBEIRAO PRETO"]
            for index in range(1, 4)
        ]
        dataframe = pd.DataFrame(rows, columns=SOURCE_COLUMNS)

        result = build_map_data(process_accidents(dataframe))

        self.assertEqual(len(result), 1)
        self.assertIs(result[0]["collision_1y_met"], True)
        self.assertIs(result[0]["collision_3y_met"], False)
        self.assertIs(result[0]["pedestrian_1y_met"], False)
        self.assertIs(result[0]["pedestrian_3y_met"], False)


class HistoricalCriteriaTests(SimpleTestCase):
    @staticmethod
    def build_accidents(rows):
        dataframe = pd.DataFrame(
            rows,
            columns=[
                "id",
                "date",
                "cluster_id",
                "accident_type",
            ],
        )
        dataframe["date"] = pd.to_datetime(
            dataframe["date"]
        )
        return dataframe

    def test_preserves_historical_eligibility_after_newer_event(self):
        accidents = self.build_accidents(
            [
                [1, "2024-01-10", 1, "COLISAO"],
                [2, "2024-04-10", 1, "COLISAO"],
                [3, "2024-08-10", 1, "COLISAO"],
                [4, "2026-07-01", 2, "CHOQUE"],
            ]
        )

        result = evaluate_historical_criteria(accidents)
        cluster = result[result["cluster_id"] == 1].iloc[0]

        self.assertTrue(cluster["collision_1y_met"])
        self.assertTrue(cluster["eligible"])

    def test_combines_events_across_dataset_boundary(self):
        accidents = self.build_accidents(
            [
                [1, "2024-07-01", 1, "COLISAO"],
                [2, "2024-12-01", 1, "COLISAO"],
                [3, "2025-06-30", 1, "COLISAO"],
            ]
        )

        result = evaluate_historical_criteria(accidents)
        cluster = result.iloc[0]

        self.assertEqual(cluster["collisions_1y"], 3)
        self.assertTrue(cluster["collision_1y_met"])

    def test_finds_seven_collisions_in_historical_three_year_window(self):
        accidents = self.build_accidents(
            [
                [1, "2018-01-01", 1, "COLISAO"],
                [2, "2020-01-01", 1, "COLISAO"],
                [3, "2020-06-01", 1, "COLISAO"],
                [4, "2021-01-01", 1, "COLISAO"],
                [5, "2021-06-01", 1, "COLISAO"],
                [6, "2022-01-01", 1, "COLISAO"],
                [7, "2022-06-01", 1, "COLISAO"],
                [8, "2023-01-01", 1, "COLISAO"],
            ]
        )

        result = evaluate_historical_criteria(accidents)
        cluster = result.iloc[0]

        self.assertEqual(cluster["collisions_3y"], 7)
        self.assertTrue(cluster["collision_3y_met"])

    def test_finds_pedestrian_criteria_in_historical_windows(self):
        accidents = self.build_accidents(
            [
                [1, "2020-01-01", 1, "ATROPELAMENTO"],
                [2, "2020-06-01", 1, "ATROPELAMENTO"],
                [3, "2022-01-01", 2, "ATROPELAMENTO"],
                [4, "2022-10-01", 2, "ATROPELAMENTO"],
                [5, "2023-08-01", 2, "ATROPELAMENTO"],
                [6, "2024-07-01", 2, "ATROPELAMENTO"],
            ]
        )

        result = evaluate_historical_criteria(accidents).set_index(
            "cluster_id"
        )

        self.assertTrue(result.loc[1, "pedestrian_1y_met"])
        self.assertTrue(result.loc[2, "pedestrian_3y_met"])

    def test_does_not_combine_events_outside_valid_windows(self):
        accidents = self.build_accidents(
            [
                [1, "2015-01-01", 1, "COLISAO"],
                [2, "2017-01-02", 1, "COLISAO"],
                [3, "2019-01-03", 1, "COLISAO"],
                [4, "2015-01-01", 1, "ATROPELAMENTO"],
                [5, "2019-01-02", 1, "ATROPELAMENTO"],
            ]
        )

        result = evaluate_historical_criteria(accidents)
        cluster = result.iloc[0]

        self.assertFalse(cluster["collision_1y_met"])
        self.assertFalse(cluster["collision_3y_met"])
        self.assertFalse(cluster["pedestrian_1y_met"])
        self.assertFalse(cluster["pedestrian_3y_met"])
        self.assertFalse(cluster["eligible"])

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
        self.assertContains(response, 'id="clear-files-button"')
        self.assertContains(response, "Limpar arquivos")
        self.assertContains(response, 'id="tools-panel"', count=1)
        self.assertContains(response, 'id="data-tab"')
        self.assertContains(response, 'id="filters-tab"')
        self.assertContains(response, 'data-filter-field="collision_1y_met"')
        self.assertContains(response, 'data-filter-field="collision_3y_met"')
        self.assertContains(response, 'data-filter-field="pedestrian_1y_met"')
        self.assertContains(response, 'data-filter-field="pedestrian_3y_met"')
        self.assertContains(response, 'id="clear-filters-button"')
        self.assertContains(response, 'id="minimize-tools-panel"')
        self.assertContains(response, 'id="open-tools-panel"')
        self.assertNotContains(response, 'id="upload-panel"')
        self.assertNotContains(response, 'id="filter-panel"')
        self.assertEqual(response.context["initial_tool_tab"], "data")

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
            response.context["initial_tool_tab"],
            "filters",
        )
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
