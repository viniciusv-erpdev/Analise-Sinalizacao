"""Library HTTP/filter/pagination contract; runnable on SQLite and PostgreSQL."""
from datetime import datetime, timedelta, timezone
from html import unescape
import re
from urllib.parse import parse_qs, urlsplit
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from signaling.report_test_fixtures import ReportDataMixin, setup_report_data


@override_settings(REPORT_FINALIZATION_ENABLED=False)
class ReportLibraryTests(ReportDataMixin, TestCase):
    def setUp(self):
        setup_report_data(self)

    def rows(self, response):
        return list(response.context["page_obj"].object_list)

    def test_anonymous_redirect_and_no_permission_or_download_only_forbidden(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.client.force_login(self.owner)
        for download in (False, True):
            if download:
                self.owner.user_permissions.add(Permission.objects.get(codename="download_official_reports"))
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertFalse(any('"signaling_technicalreport' in query["sql"].lower() for query in queries))

    def test_authorized_disabled_conversion_and_metadata_only(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RTSV-2026-0001")
        self.assertContains(response, "<td>archived-user</td>", html=True)
        self.assertContains(response, "01/11/2026 09:00")
        self.assertNotContains(response, "DO-NOT-EXPOSE-SNAPSHOT")
        self.assertNotContains(response, "/private/archive")
        self.assertTrue(response["Cache-Control"].find("no-store") >= 0)
        self.assertIn("Cookie", response["Vary"])

    def test_latest_published_version_not_newer_failed_or_processing_versions(self):
        self.make_version(self.report, 2, state="PROCESSING", author="SECRET PENDING")
        self.make_version(self.report, 3, author="Latest Author")
        self.make_version(self.report, 4, state="FAILED", author="SECRET FAILED")
        self.make_report(2, published=False)
        response = self.client.get(self.url)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertEqual(self.rows(response)[0].published_version, 3)
        self.assertEqual(self.rows(response)[0].historical_author["full_name"], "Latest Author")
        self.assertNotContains(response, "SECRET")
        self.assertNotContains(response, "RTSV-2026-0002")

    def test_filters_use_only_latest_published_version_metadata(self):
        latest = self.instant + timedelta(days=2)
        self.make_version(self.report, 2, issued=latest, author="Latest Published Author")
        self.make_version(self.report, 3, state="PROCESSING", author="Pending Author")
        for query in ({"author": "Autora Historica"}, {"author": "Pending Author"},
                      {"issued_to": "2026-11-01"}):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.url, query).context["page_obj"].paginator.count, 0)
        response = self.client.get(self.url, {"author": "Latest Published", "issued_from": "2026-11-03"})
        self.assertEqual([row.pk for row in self.rows(response)], [self.report.pk])
        self.assertEqual(self.rows(response)[0].published_version, 2)

    def test_ordering_is_emission_descending_with_deterministic_number_ties(self):
        second = self.make_report(2)
        third = self.make_report(3)
        newest = self.make_report(4, issued=self.instant+timedelta(hours=1))
        expected = [newest.pk, third.pk, second.pk, self.report.pk]
        for _ in range(2):
            self.assertEqual([row.pk for row in self.rows(self.client.get(self.url))], expected)

    def test_valid_filters_individually_and_combined(self):
        older = self.make_report(2, year=2025, issued=self.instant-timedelta(days=3), author="Other", waypoint=9999)
        filters = {"number":"RTSV-2026-0001", "year":"2026", "issued_from":"2026-11-01",
                   "issued_to":"2026-11-01", "author":"autora", "waypoint":str(self.point.pk)}
        for query in [{key:value} for key,value in filters.items()] + [filters]:
            with self.subTest(query=query):
                response = self.client.get(self.url, query)
                self.assertEqual(response.status_code, 200)
                expected = [self.report.pk, older.pk] if query == {"issued_to":"2026-11-01"} else [self.report.pk]
                self.assertEqual([row.pk for row in self.rows(response)], expected)
        self.assertEqual(self.client.get(self.url, {"author":"archived-user"}).context["page_obj"].paginator.count, 2)

    def test_date_filters_use_sao_paulo_inclusive_boundaries(self):
        self.make_report(2, year=2027, issued=datetime(2027,1,1,1,30,tzinfo=timezone.utc))
        response = self.client.get(self.url, {"issued_from":"2026-12-31", "issued_to":"2026-12-31"})
        self.assertEqual([row.sequence for row in self.rows(response)], [2])
        self.assertContains(response, "31/12/2026 22:30")
        self.assertEqual(self.client.get(self.url, {"issued_from":"2027-01-01"}).context["page_obj"].paginator.count, 0)

    def test_invalid_filters_return_400_without_report_queries(self):
        cases = [{"year":"bad"}, {"year":"0"}, {"year":"10000"}, {"number":"RTSV-2026-1"},
                 {"number":"RTSV-0000-0000"}, {"issued_from":"2026-02-30"},
                 {"issued_from":"2026-11-02", "issued_to":"2026-11-01"}, {"waypoint":"-1"},
                 {"waypoint":"1 OR 1=1"}, {"author":"x"*201}, {"year":["2025","2026"]}]
        for query in cases:
            with self.subTest(query=query), CaptureQueriesContext(connection) as queries:
                response = self.client.get(self.url, query)
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, "RTSV-2026-0001", status_code=400)
            self.assertFalse(any('"signaling_technicalreport' in query["sql"].lower() for query in queries))

    def test_valid_unmatched_or_contradictory_filters_show_empty_result(self):
        response = self.client.get(self.url, {"number":"RTSV-2026-0001", "year":"2025"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertContains(response, "Nenhum relat")
        self.assertNotContains(response, "Revise os filtros")
        self.assertEqual(self.client.get(self.url, {"author":"' OR 1=1 --"}).context["page_obj"].paginator.count, 0)

    def test_twenty_rows_per_page_and_filters_preserved_in_links(self):
        for number in range(2,22):
            self.make_report(number)
        query = {"author":"Autora", "year":"2026", "waypoint":str(self.point.pk)}
        response = self.client.get(self.url, query)
        self.assertEqual(len(self.rows(response)), 20)
        self.assertEqual(response.context["page_obj"].paginator.count, 21)
        links = [parse_qs(urlsplit(unescape(href)).query) for href in re.findall(r'href="([^"]+)"', response.content.decode())]
        next_query = next(link for link in links if link.get("page") == ["2"])
        for name,value in query.items():
            self.assertEqual(next_query[name], [value])
        response = self.client.get(self.url, query | {"page":"2"})
        self.assertEqual(len(self.rows(response)), 1)
        self.assertEqual(self.rows(response)[0].pk, self.report.pk)

    def test_invalid_pages_are_404(self):
        for page in ("0", "-1", "abc", "999", "999999999999", ["1","2"]):
            with self.subTest(page=page):
                self.assertEqual(self.client.get(self.url, {"page":page}).status_code, 404)

    def test_history_and_filters_survive_original_user_and_point_deletion(self):
        point_id = self.point.pk
        self.owner.delete()
        self.point.delete()
        response = self.client.get(self.url, {"author":"Historica", "waypoint":str(point_id)})
        self.assertEqual([row.pk for row in self.rows(response)], [self.report.pk])
        self.assertContains(response, "<td>archived-user</td>", html=True)

    def test_navbar_link_only_with_view_permission_on_map_and_library(self):
        self.assertContains(self.client.get(reverse("analysis")), f'href="{self.url}"')
        self.assertContains(self.client.get(self.url), f'href="{self.url}"')
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse("analysis")), f'href="{self.url}"')
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("analysis")), f'href="{self.url}"')

    def test_historical_author_text_is_html_escaped(self):
        self.make_version(self.report, 2, username="<script>alert(1)</script>")
        response = self.client.get(self.url)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_query_count_is_bounded_and_no_snapshots_selected(self):
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url)
        for number in range(2,22):
            self.make_report(number)
        with CaptureQueriesContext(connection) as large:
            self.client.get(self.url)
        self.assertEqual(len(small), len(large))
        self.assertFalse(any('"snapshot"' in query["sql"].lower() for query in large))

    def test_historical_username_preferred_without_current_auth_lookup(self):
        self.owner.username = "renamed-current-user"
        self.owner.save(update_fields=["username"])
        response = self.client.get(self.url)
        self.assertContains(response, "<td>archived-user</td>", html=True)
        self.assertNotContains(response, "Autora Historica")
        self.assertNotContains(response, "renamed-current-user")
        self.assertEqual(self.client.get(self.url, {"author": "Autora Historica"}).context["page_obj"].paginator.count, 1)

    def test_historical_author_fallbacks(self):
        self.make_version(self.report, 2, username="", author="Historical fallback")
        self.assertContains(self.client.get(self.url), "<td>Historical fallback</td>", html=True)
        self.make_version(self.report, 3, username="", author="")
        self.assertContains(self.client.get(self.url), "<td>N\u00e3o informado</td>", html=True)

    def test_accessible_existing_folder_icon_and_map_button(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'src="/static/icons/signaling/folder.svg"')
        self.assertContains(response, 'aria-label="Relat&#243;rios oficiais"')
        self.assertContains(response, 'title="Relat&#243;rios oficiais"')
        self.assertContains(response, f'class="report-library__back" href="{reverse("analysis")}"')

    def test_post_is_not_an_operation(self):
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)
