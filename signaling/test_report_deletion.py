"""Deletion contract/IO fault tests; SQLite mocks only the locking-backend guard.
Real row locks and publication races live in test_report_deletion_postgresql.
"""
from contextlib import contextmanager
import hashlib
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
from django.contrib.auth.models import Permission, Group
from django.core.management import call_command
from django.db import DatabaseError, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from signaling import report_deletion as service, report_finalization as finalization
from signaling.models import (TechnicalReport, TechnicalReportVersion, ReportArtifact,
    ReportFinalizationAttempt as Attempt, ReportAnnualCounter, ReportDeletion, DeletedReportKey)
from signaling.report_storage import PrivateReportStorage, ArtifactStorageError
from signaling.report_test_fixtures import ReportDataMixin, setup_report_data


class ReportDeletionTests(ReportDataMixin, TransactionTestCase):
    def setUp(self):
        setup_report_data(self)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(REPORT_PRIVATE_ROOT=self.temp.name, REPORT_FINALIZATION_ENABLED=False)
        override.enable(); self.addCleanup(override.disable)
        from django.db import connection
        if connection.vendor == "sqlite":
            guard = patch("signaling.reservations._require_locking_backend")
            guard.start(); self.addCleanup(guard.stop)
        self.reader.user_permissions.add(Permission.objects.get(codename="delete_official_reports"))
        self.storage = PrivateReportStorage()
        self.version = self.report.versions.get()
        self.keys = [self.artifact(self.version, kind, ext) for kind, ext in [("PDF","pdf"),("DOCX","docx"),("PHOTO","png")]]
        self.operation = uuid4()
        self.delete_url = reverse("signaling:delete-official-report", args=[self.report.pk])

    def artifact(self, version, kind, extension):
        key = f"{version.pk}/{uuid4()}/{uuid4()}.{extension}"
        data = b"synthetic private bytes"
        self.storage.save(key, data)
        ReportArtifact.objects.create(version=version, kind=kind, storage_key=key, size=len(data),
            sha256=hashlib.sha256(data).hexdigest(), content_type="application/octet-stream", download_name="synthetic."+extension)
        return key

    def post(self, **changes):
        return self.client.post(self.delete_url, {"operation_id":str(self.operation),
            "confirm_number":self.report.official_number, **changes}, content_type="application/json")

    def test_nonstaff_delete_only_permission_removes_all_versions_files_and_preserves_audit(self):
        self.reader.user_permissions.remove(Permission.objects.get(codename="view_official_reports"))
        self.assertFalse(self.reader.is_staff)
        second = self.make_version(self.report,2)
        self.keys.append(self.artifact(second,"PDF","pdf"))
        key = self.version.attempt.idempotency_key
        response = self.post()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["cleanup_state"],"COMPLETE")
        self.assertFalse(TechnicalReport.objects.exists())
        self.assertFalse(TechnicalReportVersion.objects.exists())
        self.assertFalse(Attempt.objects.exists())
        self.assertFalse(ReportArtifact.objects.exists())
        self.assertTrue(all(not (self.storage.root / k).exists() for k in self.keys))
        audit = ReportDeletion.objects.get()
        self.assertEqual(audit.official_number,"RTSV-2026-0001")
        self.assertEqual(audit.deleted_by_id,self.reader.pk)
        self.assertEqual(audit.pending_keys,[]); self.assertEqual(audit.version_ids,[])
        self.assertEqual(audit.retired_keys.count(),2)
        with self.assertRaises(finalization.FinalizationError) as caught:
            finalization._existing(key,self.owner.pk,"0"*64)
        self.assertEqual(caught.exception.code,"report_deleted")
        self.reader.delete();audit.refresh_from_db()
        self.assertIsNone(audit.deleted_by_id);self.assertEqual(audit.deleted_by_username,"reader")

    def test_anonymous_reader_only_and_staff_without_permission_are_denied(self):
        self.client.logout();self.assertEqual(self.post().status_code,401)
        self.client.force_login(self.reader)
        self.reader.user_permissions.remove(Permission.objects.get(codename="delete_official_reports"))
        for staff in (False, True):
            self.reader.is_staff=staff;self.reader.save(update_fields=["is_staff"])
            self.assertEqual(self.post().status_code,403)
        self.assertTrue(TechnicalReport.objects.exists())

    def test_get_csrf_confirmation_and_payload(self):
        self.assertEqual(self.client.get(self.delete_url).status_code,405)
        strict = Client(enforce_csrf_checks=True);strict.force_login(self.reader)
        self.assertEqual(strict.post(self.delete_url,{},content_type="application/json").status_code,403)
        self.assertEqual(self.post(confirm_number="RTSV-2026-9999").status_code,400)
        self.assertEqual(self.post(operation_id="invalid").status_code,400)
        self.assertFalse(ReportDeletion.objects.exists())

    def test_repeat_same_or_different_operation_does_not_duplicate_audit(self):
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.post(operation_id=str(uuid4())).status_code,200)
        self.assertEqual(ReportDeletion.objects.count(),1)
        self.delete_url=reverse("signaling:delete-official-report",args=[uuid4()])
        self.assertEqual(self.post().status_code,409) # same operation cannot delete another report
        self.operation=uuid4();self.assertEqual(self.post().status_code,404)

    def test_counter_never_reuses_deleted_number(self):
        ReportAnnualCounter.objects.create(year=2026,last_reserved=8)
        self.assertEqual(self.post().status_code,200)
        with transaction.atomic():
            self.assertEqual(finalization._counter(2026),9)

    def test_missing_counter_is_preserved_at_least_to_deleted_sequence(self):
        self.assertEqual(self.post().status_code,200)
        with transaction.atomic():self.assertEqual(finalization._counter(2026),2)

    def test_active_publication_blocks_all_deletion_even_when_overdue(self):
        self.make_version(self.report,2,state="PROCESSING")
        response=self.post();self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()["code"],"publication_in_progress")
        self.assertFalse(ReportDeletion.objects.exists())
        self.assertTrue(all((self.storage.root/k).exists() for k in self.keys))

    def test_other_reports_waypoint_draft_and_history_are_preserved(self):
        other=self.make_report(2); other_version=other.versions.get()
        other_key=self.artifact(other_version,"PDF","pdf")
        self.assertEqual(self.post().status_code,200)
        self.assertTrue(TechnicalReport.objects.filter(pk=other.pk).exists())
        self.assertTrue((self.storage.root/other_key).exists())
        self.assertTrue(type(self.point).objects.filter(pk=self.point.pk).exists())

    def test_file_failure_is_explicit_and_repeated_request_recovers(self):
        original=PrivateReportStorage.delete
        count=0
        def fail_second(storage,key):
            nonlocal count
            count+=1
            if count==2:raise ArtifactStorageError("secret/path must not leak")
            return original(storage,key)
        with patch.object(PrivateReportStorage,"delete",fail_second):
            response=self.post()
        self.assertEqual(response.status_code,202)
        self.assertTrue(response.json()["report_deleted"])
        self.assertNotIn("secret",response.content.decode())
        self.assertFalse(TechnicalReport.objects.exists())
        audit=ReportDeletion.objects.get();self.assertEqual(audit.cleanup_state,"FAILED")
        self.assertTrue(audit.pending_keys)
        self.assertEqual(self.post().status_code,200)
        self.assertTrue(all(not(self.storage.root/k).exists() for k in self.keys))

    def test_missing_files_and_unregistered_old_execution_files_are_cleaned(self):
        self.storage.delete(self.keys[0])
        orphan=f"{self.version.pk}/{uuid4()}/{uuid4()}.docx"
        self.storage.save(orphan,b"old unreferenced derivative")
        self.assertEqual(self.post().status_code,200)
        self.assertFalse((self.storage.root/orphan).exists())

    def test_invalid_or_foreign_namespace_rolls_back_before_unlink(self):
        artifact=ReportArtifact.objects.first()
        for key in ("../outside.pdf",f"{uuid4()}/{uuid4()}/{uuid4()}.pdf"):
            artifact.storage_key=key;artifact.save(update_fields=["storage_key"])
            self.assertEqual(self.post().status_code,409)
            self.assertTrue(TechnicalReport.objects.exists());self.assertFalse(ReportDeletion.objects.exists())
            self.assertTrue(all((self.storage.root/k).exists() for k in self.keys))

    def test_database_failure_rolls_back_metadata_and_never_unlinks(self):
        with patch.object(TechnicalReport,"delete",side_effect=DatabaseError("private database detail")), patch.object(PrivateReportStorage,"delete") as unlink:
            self.assertEqual(self.post().status_code,503);unlink.assert_not_called()
        self.assertTrue(TechnicalReport.objects.exists());self.assertFalse(ReportDeletion.objects.exists())
        self.assertEqual(Attempt.objects.count(),1)

    def test_commit_acknowledgement_failure_keeps_files_and_retry_recovers(self):
        atomic=transaction.atomic
        first=True
        @contextmanager
        def ambiguous(*args,**kwargs):
            nonlocal first
            outer=first and not service.connection.in_atomic_block
            if outer:first=False
            with atomic(*args,**kwargs):yield
            if outer:raise DatabaseError("ambiguous commit")
        with patch.object(service.transaction,"atomic",ambiguous),patch.object(PrivateReportStorage,"delete") as unlink:
            self.assertEqual(self.post().status_code,503);unlink.assert_not_called()
        self.assertFalse(TechnicalReport.objects.exists());self.assertTrue(ReportDeletion.objects.exists())
        self.assertTrue(all((self.storage.root/k).exists() for k in self.keys))
        self.assertEqual(self.post().status_code,200)

    def test_recovery_command_is_read_only_by_default(self):
        with patch.object(PrivateReportStorage,"delete",side_effect=ArtifactStorageError("failure")):
            self.assertEqual(self.post().status_code,202)
        output=StringIO();call_command("cleanup_report_deletions",stdout=output)
        self.assertIn("Read-only",output.getvalue())
        self.assertTrue(all((self.storage.root/k).exists() for k in self.keys))
        call_command("cleanup_report_deletions",apply=True,operation=str(self.operation),stdout=StringIO())
        self.assertEqual(ReportDeletion.objects.get().cleanup_state,"COMPLETE")

    def test_no_automatic_public_group_grants(self):
        group,_=Group.objects.get_or_create(name="analista")
        self.assertFalse(group.permissions.filter(codename="delete_official_reports").exists())
        from accounts.services import register_analyst
        from django.contrib.auth import get_user_model
        from types import SimpleNamespace
        user=get_user_model()(username="public-no-delete")
        user.set_unusable_password()
        created=register_analyst(SimpleNamespace(save=lambda commit:user))
        self.assertFalse(created.has_perm("signaling.delete_official_reports"))

    def test_recovery_never_deletes_referenced_file_from_another_report(self):
        with patch.object(PrivateReportStorage,"delete",side_effect=ArtifactStorageError("failure")):
            self.assertEqual(self.post().status_code,202)
        other=self.make_report(2);version=other.versions.get()
        other_key=self.artifact(version,"PDF","pdf")
        audit=ReportDeletion.objects.get()
        audit.pending_keys=[other_key];audit.version_ids=[str(version.pk)]
        audit.save(update_fields=["pending_keys","version_ids"])
        result=service.cleanup_deletion(operation_id=audit.pk)
        self.assertEqual(result.cleanup_state,"FAILED")
        self.assertTrue((self.storage.root/other_key).exists())

    def test_deleted_attempt_cannot_write_new_artifacts(self):
        attempt=self.version.attempt
        self.assertEqual(self.post().status_code,200)
        with self.assertRaises(finalization.FinalizationError),patch.object(PrivateReportStorage,"save") as save:
            finalization._store(attempt,self.storage,"PDF",b"late bytes")
        save.assert_not_called()

    def test_removed_report_is_not_readable_or_downloadable(self):
        self.reader.user_permissions.add(Permission.objects.get(codename="download_official_reports"))
        artifact=ReportArtifact.objects.filter(kind="PDF").get()
        detail=reverse("signaling:report-detail",args=[self.report.pk])
        download=reverse("signaling:report-artifact-download",args=[self.report.pk,1,artifact.pk])
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.client.get(detail).status_code,404)
        self.assertEqual(self.client.get(download).status_code,404)
        self.assertNotContains(self.client.get(self.url),self.report.official_number)

    def test_unpublished_report_is_outside_deletion_scope(self):
        pending=self.make_report(2,published=False)
        self.delete_url=reverse("signaling:delete-official-report",args=[pending.pk])
        response=self.post(confirm_number=pending.official_number)
        self.assertEqual(response.status_code,404)
        self.assertTrue(TechnicalReport.objects.filter(pk=pending.pk).exists())

    def test_cleanup_database_failure_after_unlink_is_recoverable(self):
        original=ReportDeletion.save
        def fail_cleanup(audit,*args,**kwargs):
            if not audit._state.adding:raise DatabaseError("cleanup commit unavailable")
            return original(audit,*args,**kwargs)
        with patch.object(ReportDeletion,"save",fail_cleanup):
            self.assertEqual(self.post().status_code,503)
        self.assertFalse(TechnicalReport.objects.exists())
        audit=ReportDeletion.objects.get()
        self.assertEqual(audit.cleanup_state,"PENDING");self.assertTrue(audit.pending_keys)
        self.assertTrue(all(not(self.storage.root/k).exists() for k in self.keys))
        self.assertEqual(self.post().status_code,200)
        audit.refresh_from_db();self.assertEqual(audit.cleanup_state,"COMPLETE")

    def test_deletion_does_not_depend_on_original_waypoint_or_author(self):
        self.point.delete();self.owner.delete()
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(ReportDeletion.objects.get().official_number,"RTSV-2026-0001")

    def test_nonstaff_ui_csrf_delete_refreshes_library_and_preserves_other_report(self):
        self.reader.user_permissions.add(Permission.objects.get(codename="download_official_reports"))
        other = self.make_report(2)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.reader)
        detail = strict.get(reverse("signaling:report-detail", args=[self.report.pk]))
        self.assertFalse(self.reader.is_staff)
        self.assertContains(detail, 'data-delete-open')
        from django.conf import settings
        token = strict.cookies[settings.CSRF_COOKIE_NAME].value
        response = strict.post(self.delete_url, {"operation_id":str(self.operation),
            "confirm_number":self.report.official_number}, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,200)
        library = strict.get(self.url)
        self.assertNotContains(library,self.report.official_number)
        self.assertContains(library,other.official_number)
        self.assertEqual(strict.get(reverse("signaling:report-detail",args=[self.report.pk])).status_code,404)
