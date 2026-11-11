"""Real PostgreSQL deletion/attempt-lock concurrency. No simulated row locks."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from tempfile import TemporaryDirectory
from unittest import skipUnless
from uuid import uuid4
from django.contrib.auth.models import Permission
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from signaling import report_deletion as service
from signaling.models import (ReportDeletion, TechnicalReport, ReportFinalizationAttempt as Attempt)
from signaling.report_storage import PrivateReportStorage
from signaling.report_test_fixtures import ReportDataMixin, setup_report_data
from signaling import test_reservation_concurrency as core


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL and isolated test database")
class ReportDeletionPostgreSQLTests(ReportDataMixin, TransactionTestCase):
    submit = core.PostgreSQLReservationConcurrencyTests.submit
    wait_for_lock = core.PostgreSQLReservationConcurrencyTests.wait_for_lock

    def setUp(self):
        setup_report_data(self)
        self.reader.user_permissions.add(Permission.objects.get(codename="delete_official_reports"))
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        override=override_settings(REPORT_PRIVATE_ROOT=self.temp.name)
        override.enable();self.addCleanup(override.disable)
        self.executor=ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.executor.shutdown, wait=True, cancel_futures=True)
        self.operation=uuid4()

    def delete(self):
        return service.delete_report(user=self.reader,report_id=self.report.pk,operation_id=self.operation,
                                      confirm_number=self.report.official_number)

    def test_two_concurrent_deletions_preserve_one_audit_and_recover_repeated_operation(self):
        barrier=Barrier(3)
        def run():
            try:return self.delete()
            except service.ReportDeletionError as error:return error.code
        one,_=self.submit(run,barrier);two,_=self.submit(run,barrier)
        barrier.wait(timeout=10);results=[one.result(timeout=12),two.result(timeout=12)]
        self.assertTrue(any(isinstance(item,ReportDeletion) for item in results))
        self.assertEqual(ReportDeletion.objects.count(),1)
        self.assertFalse(TechnicalReport.objects.filter(pk=self.report.pk).exists())
        self.assertEqual(self.delete().cleanup_state,"COMPLETE")

    def test_publication_holding_attempt_lock_causes_conflict_without_deadlock(self):
        attempt=self.report.versions.get().attempt
        with transaction.atomic():
            Attempt.objects.select_for_update().get(pk=attempt.pk)
            # Same row lock held by the publishing transaction before its final fence.
            future,_=self.submit(lambda:self._conflict())
            self.assertEqual(future.result(timeout=12),"deletion_conflict")
        self.assertTrue(TechnicalReport.objects.filter(pk=self.report.pk).exists())
        self.assertFalse(ReportDeletion.objects.exists())
        self.assertEqual(self.delete().cleanup_state,"COMPLETE")

    def _conflict(self):
        try:self.delete()
        except service.ReportDeletionError as error:return error.code
        return "unexpected deletion"

    def test_pending_new_version_is_not_deleted_during_publication(self):
        self.make_version(self.report,2,state="STORING")
        with self.assertRaises(service.ReportDeletionError) as caught:self.delete()
        self.assertEqual(caught.exception.code,"publication_in_progress")
        self.assertEqual(self.report.versions.count(),2)

    def test_permission_revoked_while_waiting_on_counter_prevents_commit(self):
        from signaling.models import ReportAnnualCounter
        ReportAnnualCounter.objects.create(year=self.report.year,last_reserved=self.report.sequence)
        with transaction.atomic():
            ReportAnnualCounter.objects.select_for_update().get(year=self.report.year)
            future,pid=self.submit(lambda:self._conflict())
            self.wait_for_lock(pid,future)
            self.reader.user_permissions.clear()
        self.assertEqual(future.result(timeout=12),"permission_denied")
        self.assertTrue(TechnicalReport.objects.filter(pk=self.report.pk).exists())
        self.assertFalse(ReportDeletion.objects.exists())
