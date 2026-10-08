import json
from decimal import Decimal
from http.client import IncompleteRead
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from django.test import SimpleTestCase

from signaling.overpass import (
    AMENITY_LABELS, HTTP_TIMEOUT_SECONDS, MAX_RESPONSE_BYTES,
    InvalidPGTLocation, OverpassUnavailable, build_pgt_query, find_nearby_pgts,
)


class OverpassTests(SimpleTestCase):
    def setUp(self):
        self.http = patch("signaling.overpass.urlopen").start()
        self.addCleanup(patch.stopall)
        self.response = MagicMock()
        self.response.status = 200
        self.http.return_value.__enter__.return_value = self.response

    def search(self, payload=None):
        if payload is not None:
            self.response.read.return_value = json.dumps(payload).encode("utf-8")
        return find_nearby_pgts(
            latitude=Decimal("-21.170123"),
            longitude=Decimal("-47.810456"),
            radius_meters=120,
        )

    def element(self, amenity="hospital", name="Hospital X", kind="node"):
        return {"type": kind, "tags": {"amenity": amenity, "name": name}}

    def test_all_seven_amenities_and_all_element_types(self):
        for amenity, label in AMENITY_LABELS.items():
            for kind in ("node", "way", "relation"):
                with self.subTest(amenity=amenity, kind=kind):
                    results = self.search({"elements": [self.element(amenity, "São José", kind)]})
                    self.assertEqual(results, [f"{label}: São José"])

    def test_single_query_uses_persisted_geometry_and_explicit_timeout(self):
        self.search({"elements": []})
        self.http.assert_called_once()
        request = self.http.call_args.args[0]
        self.assertEqual(self.http.call_args.kwargs, {"timeout": HTTP_TIMEOUT_SECONDS})
        query = parse_qs(request.data.decode())["data"][0]
        self.assertIn("nwr(around:120,-21.170123,-47.810456)", query)
        self.assertIn("[timeout:10]", query)
        self.assertIn('["amenity"~"^(hospital|clinic|doctors|university|college|school|kindergarten)$"]', query)
        self.assertTrue(query.endswith("out tags;"))
        self.assertEqual(request.method, "POST")

    def test_ignores_missing_blank_nontext_name_and_unsupported_amenity(self):
        elements = [self.element(name=value) for value in (None, "", "  ", 123)]
        elements += [
            {"type": "way", "tags": {"amenity": "hospital"}},
            self.element("restaurant"),
            self.element(name="A" * 301),
            self.element(name="Inválido\x00"),
        ]
        self.assertEqual(self.search({"elements": elements}), [])

    def test_deduplicates_normalized_category_and_name_without_fuzzy_matching(self):
        elements = [
            self.element(name="Hospital X"),
            self.element(name=" HOSPITAL   X ", kind="way"),
            self.element("clinic", "Hospital X", "relation"),
            self.element(name="Hospital Y"),
            self.element("school", "Hospital X"),
        ]
        self.assertEqual(self.search({"elements": elements}), [
            "🏥 Unidade de Saúde: Hospital X",
            "🏥 Unidade de Saúde: Hospital Y",
            "🎓 Unidade escolar: Hospital X",
        ])

    def test_empty_response(self):
        self.assertEqual(self.search({"elements": []}), [])

    def test_network_timeout_connection_and_incomplete_response(self):
        for error in (
            TimeoutError(), URLError("offline"), ConnectionResetError(),
            IncompleteRead(b"partial"),
        ):
            with self.subTest(error=type(error).__name__):
                self.http.side_effect = error
                with self.assertRaises(OverpassUnavailable):
                    self.search()

    def test_http_errors_including_rate_limit_and_server_failure(self):
        for status in (400, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.http.side_effect = HTTPError("https://example.invalid", status, "error", {}, BytesIO())
                with self.assertRaises(OverpassUnavailable):
                    self.search()

    def test_unexpected_http_status(self):
        for status in (201, 204, 302):
            with self.subTest(status=status):
                self.response.status = status
                with self.assertRaises(OverpassUnavailable):
                    self.search({"elements": []})

    def test_invalid_json_encoding_and_oversized_response(self):
        for content in (b"<html>Error</html>", b"\xff", b"x" * (MAX_RESPONSE_BYTES + 1)):
            with self.subTest(length=len(content)):
                self.response.read.return_value = content
                with self.assertRaises(OverpassUnavailable):
                    self.search()

    def test_unexpected_structure_and_overpass_runtime_error(self):
        for payload in (
            [], {}, {"elements": None}, {"elements": {}},
            {"elements": [None]}, {"elements": [{"tags": []}]},
            {"elements": [], "remark": "runtime error: timeout"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(OverpassUnavailable):
                    self.search(payload)

    def test_invalid_location_never_calls_network(self):
        valid = {"latitude": 0, "longitude": 0, "radius_meters": 50}
        for field, value in (
            ("latitude", None), ("latitude", 91), ("latitude", float("nan")),
            ("longitude", -181), ("longitude", float("inf")),
            ("radius_meters", 9), ("radius_meters", 301), ("radius_meters", 50.5),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(InvalidPGTLocation):
                    find_nearby_pgts(**{**valid, field: value})
        self.http.assert_not_called()

    def test_all_supported_radius_boundaries(self):
        for radius in (10, 50, 300):
            self.assertIn(
                f"around:{radius},",
                build_pgt_query(latitude=0, longitude=0, radius_meters=radius),
            )
