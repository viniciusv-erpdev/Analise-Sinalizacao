"""Reconciliation uses only disposable DB fixtures and exclusive temporary files."""
from datetime import timedelta
from io import StringIO
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from signaling.models import (TechnicalReport, TechnicalReportVersion, ReportArtifact,
                              ReportFinalizationAttempt as Attempt)
from signaling.report_storage import PrivateReportStorage


class ReportReconciliationTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(REPORT_PRIVATE_ROOT=self.temp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.storage = PrivateReportStorage()
        self.report = TechnicalReport.objects.create(year=2026, sequence=1, waypoint_history={}, number_reserved_at=timezone.now())
        self.version = TechnicalReportVersion.objects.create(report=self.report, snapshot={}, snapshot_sha256="0"*64,
            source_sha256="0"*64, author_identity={}, issued_at=timezone.now())
        self.attempt = Attempt.objects.create(version=self.version, idempotency_key=uuid4(), request_sha256="0"*64,
            state="FAILED", deadline=timezone.now()+timedelta(hours=2))

    def file(self, *, old=True, extension="pdf"):
        key = f"{self.version.pk}/{self.attempt.execution_id}/{uuid4()}.{extension}"
        self.storage.save(key, b"synthetic")
        if old:
            timestamp = (timezone.now()-timedelta(hours=48)).timestamp()
            os.utime(Path(self.temp.name, key), (timestamp, timestamp))
        return key

    def reference(self, key, kind="PDF"):
        return ReportArtifact.objects.create(version=self.version, kind=kind, storage_key=key,
            download_name="synthetic", content_type="application/octet-stream", size=9,
            sha256=hashlib.sha256(b"synthetic").hexdigest())

    def reconcile(self, **options):
        call_command("reconcile_report_finalizations", stdout=StringIO(), **options)

    def test_aged_referenced_pdf_docx_and_photo_survive_explicit_cleanup(self):
        self.version.finalized_at = timezone.now()
        self.version.save(update_fields=["finalized_at"])
        self.report.number_assigned_at = self.version.finalized_at
        self.report.save(update_fields=["number_assigned_at"])
        Attempt.objects.filter(pk=self.attempt.pk).update(state="FINALIZED")
        keys = []
        for kind, extension in (("PDF","pdf"),("DOCX","docx"),("PHOTO","png")):
            key = self.file(extension=extension)
            self.reference(key, kind)
            keys.append(key)
        self.reconcile(delete_orphans=True)
        self.assertEqual(set(self.storage.keys()), set(keys))
        for artifact in self.version.artifacts.all():
            self.assertEqual(self.storage.read(artifact), b"synthetic")

    def test_aged_orphan_survives_dry_run(self):
        key = self.file()
        self.reconcile()
        self.assertIn(key, self.storage.keys())

    def test_only_explicit_cleanup_deletes_aged_orphan_and_retains_recent_file(self):
        old, recent = self.file(), self.file(old=False)
        self.reconcile(delete_orphans=True)
        self.assertNotIn(old, self.storage.keys())
        self.assertIn(recent, self.storage.keys())

    def test_reference_created_after_listing_prevents_deletion(self):
        key = self.file()
        original_modified_at = PrivateReportStorage.modified_at
        def modified_at(storage, candidate):
            # referenced set was already materialized; final existence query must see this.
            if candidate == key:
                self.reference(key)
            return original_modified_at(storage, candidate)
        with patch.object(PrivateReportStorage, "modified_at", modified_at):
            self.reconcile(delete_orphans=True)
        self.assertIn(key, self.storage.keys())

    def test_active_execution_files_survive_even_if_old_or_overdue(self):
        key = self.file()
        for state in ("PROCESSING", "STORING"):
            for deadline in (timezone.now()+timedelta(hours=1), timezone.now()-timedelta(hours=1)):
                Attempt.objects.filter(pk=self.attempt.pk).update(state=state, deadline=deadline)
                self.reconcile(delete_orphans=True)
                self.assertIn(key, self.storage.keys())

    def test_explicit_interruption_allows_aged_unreferenced_file_cleanup(self):
        key = self.file()
        Attempt.objects.filter(pk=self.attempt.pk).update(state="PROCESSING", deadline=timezone.now()-timedelta(hours=1))
        self.reconcile(mark_interrupted=True, delete_orphans=True)
        self.assertNotIn(key, self.storage.keys())
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.state, "INTERRUPTED")
