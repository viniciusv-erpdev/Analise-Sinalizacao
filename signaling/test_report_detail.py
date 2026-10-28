"""Read-only published report history HTTP contracts."""
from datetime import timedelta
from uuid import uuid4
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.db import connection
from django.test.utils import CaptureQueriesContext
from signaling.report_test_fixtures import ReportDataMixin, setup_report_data


@override_settings(REPORT_FINALIZATION_ENABLED=False)
class ReportDetailTests(ReportDataMixin, TestCase):
    def setUp(self):
        setup_report_data(self)

    def detail_url(self, report=None):
        return reverse("signaling:report-detail", args=[(report or self.report).pk])

    def test_multiple_versions_only_published_in_reverse_chronology(self):
        self.make_version(self.report, 2, issued=self.instant + timedelta(days=1), username="historical-v2")
        self.make_version(self.report, 3, state="PROCESSING", username="SECRET PENDING")
        self.make_version(self.report, 4, state="FAILED", username="SECRET FAILED")
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual([v.version for v in response.context["versions"]], [2, 1])
        self.assertEqual(response.context["latest_version"].version, 2)
        self.assertContains(response, 'report-version--latest', count=1)
        self.assertLess(response.content.index(b'>Vers&#227;o 2<'), response.content.index(b'>Vers&#227;o 1<'))
        self.assertContains(response, "historical-v2")
        self.assertContains(response, "0" * 64)
        self.assertContains(response, "02/11/2026 09:00")
        self.assertNotContains(response, "SECRET")
        self.assertNotContains(response, "DO-NOT-EXPOSE-SNAPSHOT")
        self.assertNotContains(response, "/private/archive")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])

    def test_missing_or_unauthorized_are_404(self):
        missing = reverse("signaling:report-detail", args=[uuid4()])
        self.assertEqual(self.client.get(missing).status_code, 404)
        self.client.logout()
        for url in (self.detail_url(), missing):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.owner)
        for permission in (None, "download_official_reports", "finalize_technicalreport"):
            self.owner.user_permissions.clear()
            if permission:
                self.owner.user_permissions.add(Permission.objects.get(codename=permission))
            for url in (self.detail_url(), missing):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_unassigned_report_and_unpublished_versions_hidden(self):
        unpublished = self.make_report(2, published=False)
        self.assertEqual(self.client.get(self.detail_url(unpublished)).status_code, 404)
        self.make_version(self.report, 2, state="FAILED")
        self.assertEqual(len(self.client.get(self.detail_url()).context["versions"]), 1)

    def test_history_survives_related_deletion_without_reservation(self):
        point_id = self.point.pk
        self.owner.delete()
        self.point.delete()
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "archived-user")
        self.assertContains(response, str(point_id))
        self.assertContains(response, self.report.official_number)

    def test_library_links_to_details_and_read_only_method(self):
        self.assertContains(self.client.get(self.url), f'href="{self.detail_url()}"')
        self.assertEqual(self.client.post(self.detail_url()).status_code, 405)

    def test_no_snapshots_artifacts_or_live_relations_loaded(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(self.detail_url()).status_code, 200)
        sql = " ".join(q["sql"].lower() for q in queries)
        self.assertNotIn('"snapshot"', sql)
        self.assertNotIn('"signaling_reportartifact"', sql)
        self.assertNotIn('"signaling_signalingpoint"', sql)

    def test_historical_author_escaped_and_full_name_fallback(self):
        self.make_version(self.report, 2, username="", author="<script>historic</script>")
        response = self.client.get(self.detail_url())
        self.assertContains(response, "&lt;script&gt;historic&lt;/script&gt;")
        self.assertNotContains(response, "<script>historic</script>")
