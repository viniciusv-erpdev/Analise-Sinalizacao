"""Real PostgreSQL, synthetic validated OS adapter. Never starts systemd units."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError, OperationalError
from django.http import QueryDict
from django.test import TransactionTestCase, override_settings

from signaling import report_supervision as service, report_executor as executor, report_admission as admission
from signaling import report_systemd_runtime as runtime, report_deletion, report_diagnostics
from signaling import test_reservation_concurrency as core
from signaling import test_report_executor_postgresql as executor_tests
from signaling.models import ReportExecutionIdentity as Identity, ReportFinalizationAttempt as Attempt, ReportPublicationSlot, WaypointReportDraft
from signaling.test_report_supervision import HOST, RELEASE, observations
from signaling.report_finalization import FinalizationError


@skipUnless(connection.vendor == "postgresql", "Requires real isolated PostgreSQL")
@override_settings(REPORT_SYSTEMD_SUPERVISION_ENABLED=True, REPORT_EXECUTOR_ENABLED=True,
                   REPORT_EXECUTOR_RELEASE_ID=RELEASE, REPORT_EXECUTOR_SYSTEMD_USER="rtsv-report")
class SupervisionPostgreSQLTests(TransactionTestCase):
    reservation_permissions = ("view_signalingpoint", "generate_signaling_report", "finalize_technicalreport")
    acquire = core.PostgreSQLReservationConcurrencyTests.acquire
    submit = core.PostgreSQLReservationConcurrencyTests.submit
    race = core.PostgreSQLReservationConcurrencyTests.race

    def setUp(self):
        core.PostgreSQLReservationConcurrencyTests.setUp(self)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(REPORT_PRIVATE_ROOT=self.temp.name,
            REPORT_LIBREOFFICE_EXECUTABLE=executor_tests.LIBREOFFICE)
        override.enable()
        self.addCleanup(override.disable)
        host = patch.object(runtime, "host_identity", return_value=HOST)
        host.start()
        self.addCleanup(host.stop)
        WaypointReportDraft.objects.create(signaling_point=self.point, inspection_address="Synthetic street",
            inspection_date="2026-10-28", inspector_name="Inspector")
        grant = self.acquire()
        with override_settings(REPORT_ADMISSION_ENABLED=True):
            self.attempt = admission.admit(point_id=self.point.pk, identity=self.identity, credentials=grant.credentials,
                user_id=self.client.session["_auth_user_id"], key=uuid4(), expected_revision=1,
                parameters=QueryDict(), analysis_state={"view_mode": "individual", "map_data": []})

    def prepare(self):
        return service.prepare(attempt_id=self.attempt.pk, expected_execution_id=self.attempt.execution_id)

    def context(self, identity):
        return service.LaunchContext(identity.pk, runtime.validate_runtime(identity, **observations(identity)))

    def test_prepare_persists_before_claim_and_replays_without_new_name(self):
        identity = self.prepare()
        self.assertEqual(self.prepare().pk, identity.pk)
        self.assertEqual(Identity.objects.count(), 1)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.state, Attempt.State.ADMITTED)
        self.assertIsNone(identity.bound_at)
        self.assertEqual(ReportPublicationSlot.objects.get().execution_id, self.attempt.execution_id)
        self.assertNotEqual(identity.execution_id, self.attempt.execution_id)

    def test_concurrent_prepare_has_one_launch_intention(self):
        def prepare():
            try:
                return self.prepare()
            except FinalizationError as error:
                return error.code
        results = self.race(prepare, prepare)
        self.assertTrue(any(isinstance(item, Identity) for item in results))
        self.assertEqual(Identity.objects.count(), 1)

    def test_claim_commits_runtime_and_fencing_together(self):
        identity = self.prepare()
        current = executor.claim(self.attempt.pk, supervision=self.context(identity))
        identity.refresh_from_db()
        self.assertIsNotNone(identity.bound_at)
        self.assertEqual(identity.execution_id, current.execution_id)
        self.assertEqual(ReportPublicationSlot.objects.get().execution_id, current.execution_id)
        with transaction.atomic():
            admission.assert_execution(current.pk, current.execution_id)
            with self.assertRaises(FinalizationError):
                admission.assert_execution(current.pk, self.attempt.execution_id)

    def test_concurrent_binding_cannot_create_two_active_invocations(self):
        identity = self.prepare()
        context = self.context(identity)
        def claim():
            try:
                return executor.claim(self.attempt.pk, supervision=context)
            except FinalizationError as error:
                return error.code
        results = self.race(claim, claim)
        self.assertEqual(sum(isinstance(item, Attempt) for item in results), 1)
        self.assertIsNotNone(Identity.objects.get().bound_at)

    def test_manual_cannot_bypass_plan_even_after_flag_disabled(self):
        self.prepare()
        with override_settings(REPORT_SYSTEMD_SUPERVISION_ENABLED=False), self.assertRaisesMessage(
                FinalizationError, "execution_supervision_required"):
            executor.claim(self.attempt.pk)

    def test_binding_rollback_keeps_admission_and_unbound_identity(self):
        identity = self.prepare()
        original = Identity.save
        def fail(identity, *args, **kwargs):
            original(identity, *args, **kwargs)
            if identity.bound_at:
                raise OperationalError("injected ambiguous binding failure")
        with patch.object(Identity, "save", fail), self.assertRaisesMessage(FinalizationError, "execution_database_state_unknown"):
            executor.execute(self.attempt.pk, supervision=self.context(identity))
        identity.refresh_from_db()
        self.attempt.refresh_from_db()
        self.assertIsNone(identity.bound_at)
        self.assertEqual(self.attempt.state, Attempt.State.ADMITTED)
        self.assertEqual(ReportPublicationSlot.objects.get().execution_id, self.attempt.execution_id)

    def test_boot_or_release_changes_never_reuse_plan(self):
        self.prepare()
        with patch.object(runtime, "host_identity", return_value=runtime.HostIdentity(HOST.host_id, uuid4())), self.assertRaisesMessage(
                FinalizationError, "supervision_plan_conflict"):
            self.prepare()
        with override_settings(REPORT_EXECUTOR_RELEASE_ID="c"*40), self.assertRaises(FinalizationError):
            self.prepare()

    def test_context_is_verified_before_claim_and_used_identity_cannot_restart(self):
        identity = self.prepare()
        context = self.context(identity)
        with patch.object(runtime, "capture", return_value=context.runtime):
            target, actual = service.context(identity.pk)
            self.assertEqual(target, self.attempt.pk)
            executor.claim(target, supervision=actual)
        with self.assertRaisesMessage(FinalizationError, "supervision_identity_already_used"):
            service.context(identity.pk)

    def test_immutable_identity_and_database_unique_names(self):
        identity = self.prepare()
        identity.unit_name = "changed.service"
        with self.assertRaises(ValidationError):
            identity.save()
        with self.assertRaises(ValidationError):
            Identity.objects.filter(pk=identity.pk).update(unit_name="changed.service")
        identity.refresh_from_db()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Identity.objects.create(attempt=self.attempt, attempt_reference=self.attempt.pk,
                expected_execution_id=uuid4(), host_id=HOST.host_id, boot_id=HOST.boot_id,
                unit_name=identity.unit_name, release_id=RELEASE, release_root=identity.release_root, service_user="rtsv-report")

    @skipUnless(executor_tests.REAL_CONVERSION, "Requires real LibreOffice and pypdf")
    def test_real_pipeline_binds_before_render_and_physical_deletion_retains_identity(self):
        identity = self.prepare()
        context = self.context(identity)
        render = executor.render_snapshot
        def checked_render(*args):
            self.assertIsNotNone(Identity.objects.get(pk=identity.pk).bound_at)
            self.assertEqual(Attempt.objects.get(pk=self.attempt.pk).execution_id, identity.execution_id)
            self.assertFalse(connection.in_atomic_block)
            return render(*args)
        with patch.object(runtime, "capture", return_value=context.runtime), patch.object(executor, "render_snapshot", side_effect=checked_render):
            result = executor.execute(self.attempt.pk, supervision=context)
        self.assertEqual(result.state, Attempt.State.FINALIZED)
        self.assertIsNone(ReportPublicationSlot.objects.get().attempt_id)
        user = get_user_model().objects.get(pk=self.client.session["_auth_user_id"])
        user.user_permissions.add(Permission.objects.get(codename="delete_official_reports"))
        report_deletion.delete_report(user=user, report_id=result.version.report_id,
            operation_id=uuid4(), confirm_number=result.version.report.official_number)
        identity.refresh_from_db()
        self.assertIsNone(identity.attempt_id)
        self.assertEqual(identity.attempt_reference, self.attempt.pk)
        self.assertIsNotNone(identity.bound_at)

    def test_diagnostic_displays_identity_but_never_termination_proof(self):
        identity = self.prepare()
        result = report_diagnostics.diagnose()
        self.assertEqual(result["operational_identities"][0]["unit_name"], identity.unit_name)
        self.assertFalse(result["recovery"]["permitted"])
        self.assertNotIn(identity.release_root, str(result))
