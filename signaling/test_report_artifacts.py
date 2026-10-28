"""Private file delivery using the Stage 6 on-disk artifact layout."""
import hashlib
import tempfile
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.db import connection
from django.urls import reverse
from signaling.report_test_fixtures import ReportDataMixin, setup_report_data
from signaling.models import ReportArtifact
from signaling.report_storage import PrivateReportStorage


@override_settings(REPORT_FINALIZATION_ENABLED=False)
class ReportArtifactTests(ReportDataMixin, TestCase):

    def setUp(self):
        setup_report_data(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(REPORT_PRIVATE_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.reader.user_permissions.add(Permission.objects.get(codename="download_official_reports"))
        self.version = self.report.versions.first()
        self.storage = PrivateReportStorage()
        self.pdf = self.artifact("PDF", ".pdf", "application/pdf", b"%PDF-1.4 synthetic EOF")
        self.docx = self.artifact("DOCX", ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"synthetic docx archive")
        self.photo = self.artifact("PHOTO", ".png", "image/png", b"synthetic original photo")

    def artifact(self, kind, suffix, mime, data, version=None):
        version = version or self.version
        key = f"{version.pk}/{uuid4()}/{uuid4()}{suffix}"
        self.storage.save(key, data)
        return ReportArtifact.objects.create(version=version, kind=kind, storage_key=key,
            size=len(data), sha256=hashlib.sha256(data).hexdigest(), content_type=mime,
            download_name="historical-original" + suffix)

    def file_url(self, artifact=None, download=False, **changes):
        artifact = artifact or self.pdf
        kwargs = dict(report_id=self.report.pk, version=artifact.version.version, artifact_id=artifact.pk)
        kwargs.update(changes)
        return reverse("signaling:report-artifact-download" if download else "signaling:report-artifact-view", kwargs=kwargs)

    def test_headers_and_original_bytes_streamed_without_reservation(self):
        for artifact in (self.pdf, self.docx, self.photo):
            for download in (True, False):
                if not download and artifact.kind == "DOCX":
                    self.assertEqual(self.client.get(self.file_url(artifact)).status_code, 404)
                    continue
                response = self.client.get(self.file_url(artifact, download))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.streaming)
                self.assertEqual(response["Content-Type"], artifact.content_type)
                self.assertTrue(response["Content-Disposition"].startswith("attachment" if download else "inline"))
                self.assertIn("private", response["Cache-Control"])
                self.assertIn("no-store", response["Cache-Control"])
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                data = b"".join(response.streaming_content)
                self.assertTrue(response.closed)
                self.assertEqual(hashlib.sha256(data).hexdigest(), artifact.sha256)
                self.assertNotIn(self.temp.name, str(response.headers))

    def test_permissions_anonymous_and_download_only(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.file_url()).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.file_url()).status_code, 404)
        self.owner.user_permissions.add(Permission.objects.get(codename="download_official_reports"))
        self.assertEqual(self.client.get(self.file_url()).status_code, 404)
        self.reader.user_permissions.remove(Permission.objects.get(codename="download_official_reports"))
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(self.file_url()).status_code, 404)
        response = self.client.get(reverse("signaling:report-detail", args=[self.report.pk]))
        self.assertNotContains(response, self.file_url())

    def test_missing_mismatched_and_unpublished_objects(self):
        for changes in ({"report_id":uuid4()}, {"version":999}, {"artifact_id":uuid4()}):
            self.assertEqual(self.client.get(self.file_url(**changes)).status_code, 404)
        other = self.make_report(2)
        self.assertEqual(self.client.get(self.file_url(report_id=other.pk)).status_code, 404)
        pending = self.make_version(self.report, 2, state="PROCESSING")
        artifact = self.artifact("PDF", ".pdf", "application/pdf", b"pending", pending)
        self.assertEqual(self.client.get(self.file_url(artifact)).status_code, 404)
        self.assertEqual(self.client.get(self.file_url(self.pdf, version=2)).status_code, 404)

    def test_missing_corrupt_same_size_and_wrong_size_fail_closed(self):
        path = Path(self.temp.name) / self.pdf.storage_key
        path.write_bytes(b"X" * self.pdf.size)
        self.assertEqual(self.client.get(self.file_url()).status_code, 404)
        path.write_bytes(b"short")
        self.assertEqual(self.client.get(self.file_url()).status_code, 404)
        path.unlink()
        self.assertEqual(self.client.get(self.file_url()).status_code, 404)

    def test_path_traversal_and_inconsistent_content_type(self):
        ReportArtifact.objects.filter(pk=self.pdf.pk).update(storage_key="../../secret.pdf")
        self.assertEqual(self.client.get(self.file_url()).status_code, 404)
        ReportArtifact.objects.filter(pk=self.docx.pk).update(content_type="text/html")
        self.assertEqual(self.client.get(self.file_url(self.docx, True)).status_code, 404)

    def test_deleted_relations_and_detail_actions(self):
        self.owner.delete()
        self.point.delete()
        response = self.client.get(reverse("signaling:report-detail", args=[self.report.pk]))
        for artifact in (self.pdf, self.docx, self.photo):
            self.assertContains(response, self.file_url(artifact, True))
        self.assertContains(response, self.file_url(self.pdf))
        self.assertContains(response, self.file_url(self.photo))
        self.assertNotContains(response, self.temp.name)
        response = self.client.get(self.file_url())
        self.assertEqual(response.status_code, 200)
        # Consume via the client wrapper so request_finished uses Django's
        # test connection handling, rather than closing the TestCase connection.
        list(response.streaming_content)
        self.assertTrue(response.closed)
        self.assertTrue(type(self.reader).objects.filter(pk=self.reader.pk).exists())

    def test_post_not_allowed_and_verified_handle_closes(self):
        self.assertEqual(self.client.post(self.file_url()).status_code, 405)
        stream = self.storage.open_verified(self.pdf)
        with patch.object(PrivateReportStorage, "open_verified", return_value=stream):
            response = self.client.get(self.file_url())
        # Consume via the client wrapper so request_finished uses Django's
        # test connection handling, rather than closing the TestCase connection.
        with patch.object(connection, "close", wraps=connection.close) as close_connection:
            list(response.streaming_content)
        close_connection.assert_not_called()
        self.assertTrue(response.closed)
        self.assertTrue(type(self.reader).objects.filter(pk=self.reader.pk).exists())
        self.assertTrue(stream.closed)

    def test_version_card_actions_and_photo_count(self):
        response = self.client.get(reverse("signaling:report-detail", args=[self.report.pk]))
        self.assertContains(response, 'class="report-version report-version--latest"', count=1)
        self.assertContains(response, 'Visualizar relat&#243;rio')
        self.assertContains(response, 'Baixar PDF')
        self.assertContains(response, 'Baixar DOCX')
        self.assertContains(response, 'Fotografias (1)')
        self.assertContains(response, 'Detalhes t&#233;cnicos')
        self.assertContains(response, f'data-copy-hash="hash-{self.version.pk}"')
        self.assertNotContains(response, '<table>')
        self.reader.user_permissions.remove(Permission.objects.get(codename="download_official_reports"))
        response = self.client.get(reverse("signaling:report-detail", args=[self.report.pk]))
        self.assertNotContains(response, self.file_url())
        self.assertNotContains(response, 'Baixar PDF')
        self.assertNotContains(response, 'Fotografias (')
        self.assertContains(response, 'Detalhes t&#233;cnicos')
