from django.http import QueryDict
from django.test import SimpleTestCase

from signaling.report_filters import (
    InvalidIndividualReportFilters,
    parse_individual_report_filters,
)


class IndividualReportFiltersTests(SimpleTestCase):
    accidents = [
        {
            "id": "1", "year": 2025, "month": 1,
            "category": "collision", "is_fatal": True,
        },
        {
            "id": "2", "year": 2025, "month": 2,
            "category": "collision", "is_fatal": False,
        },
        {
            "id": "3", "year": 2024, "month": 1,
            "category": "pedestrian", "is_fatal": False,
        },
        {
            "id": "4", "year": None, "month": None,
            "category": "crash", "is_fatal": False,
        },
    ]

    def apply(self, query: str) -> list[str]:
        filters = parse_individual_report_filters(
            QueryDict(query),
            self.accidents,
        )
        return [item["id"] for item in filters.apply(self.accidents)]

    def test_no_filters_preserves_every_accident(self):
        self.assertEqual(self.apply(""), ["1", "2", "3", "4"])

    def test_filters_year_and_optional_month(self):
        self.assertEqual(self.apply("year=2025"), ["1", "2"])
        self.assertEqual(self.apply("year=2025&month=2"), ["2"])

    def test_filters_multiple_years_and_months_with_or_inside_dimensions(self):
        self.assertEqual(
            self.apply("year=2024&year=2025&month=1&month=2"),
            ["1", "2", "3"],
        )
        self.assertEqual(self.apply("month=1"), ["1", "3"])

    def test_categories_use_or_and_empty_means_all(self):
        self.assertEqual(
            self.apply("category=collision&category=pedestrian"),
            ["1", "2", "3"],
        )
        self.assertEqual(self.apply(""), ["1", "2", "3", "4"])

    def test_gravity_filters_are_exclusive(self):
        self.assertEqual(self.apply("gravity=fatal"), ["1"])
        self.assertEqual(
            self.apply("gravity=non_fatal"),
            ["2", "3", "4"],
        )

    def test_dimensions_are_combined_with_and(self):
        self.assertEqual(
            self.apply(
                "year=2025&month=1&category=collision&gravity=fatal"
            ),
            ["1"],
        )
        self.assertEqual(
            self.apply(
                "year=2025&month=2&category=pedestrian&gravity=fatal"
            ),
            [],
        )

    def test_invalid_or_stale_parameters_are_rejected(self):
        invalid_queries = (
            "year=text",
            "year=2025&month=13",
            "year=1999",
            "year=2025&month=12",
            "category=unknown",
            "gravity=unknown",
        )
        for query in invalid_queries:
            with self.subTest(query=query):
                with self.assertRaises(InvalidIndividualReportFilters):
                    parse_individual_report_filters(
                        QueryDict(query),
                        self.accidents,
                    )

        with self.assertRaises(InvalidIndividualReportFilters):
            parse_individual_report_filters(
                QueryDict("analysis=old"),
                self.accidents,
                current_analysis_id="current",
            )

    def test_presentation_uses_validated_values(self):
        filters = parse_individual_report_filters(
            QueryDict(
                "year=2025&month=1&category=pedestrian&"
                "category=collision&gravity=fatal"
            ),
            self.accidents,
        )

        self.assertEqual(filters.presentation(), {
            "period": "Anos: 2025. Meses: Janeiro.",
            "categories": "Atropelamento, Colisão",
            "gravity": "Somente fatais",
        })

    def test_presentation_describes_multiple_periods_and_unrestricted_values(self):
        filters = parse_individual_report_filters(
            QueryDict("year=2024&year=2025&month=1&month=2"),
            self.accidents,
        )
        self.assertEqual(
            filters.presentation()["period"],
            "Anos: 2024 e 2025. Meses: Janeiro e Fevereiro.",
        )
        self.assertEqual(
            parse_individual_report_filters(
                QueryDict("year=2025"), self.accidents
            ).presentation()["period"],
            "Anos: 2025. Meses: Todos os meses disponíveis.",
        )
        self.assertEqual(
            parse_individual_report_filters(
                QueryDict(""), self.accidents
            ).presentation()["period"],
            "Todos os períodos disponíveis",
        )
