"""Real PostgreSQL transactions. No systemd calls or document publication."""
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from unittest import skipUnless
from unittest.mock import patch
from uuid import UUID, uuid4

from django.db import connection, OperationalError, transaction, IntegrityError
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.test import TransactionTestCase, override_settings

from signaling import report_operations as service, report_admission as admission
from signaling import report_supervision as supervision, report_diagnostics as diagnostics
from signaling import report_systemd_runtime as runtime, report_executor as executor
from signaling import test_reservation_concurrency as core
from signaling.test_report_supervision import HOST, RELEASE
from signaling.test_report_supervision import observations
from signaling.models import (ReportLaunch as Launch, ReportReleaseAuthorization as Release,
    ReportDeploymentBarrier as Barrier, ReportOperationalEvent as Event,
    ReportFinalizationAttempt as Attempt, ReportPublicationSlot as Slot,
    WaypointReportDraft, ReportAnnualCounter, ReportExecutionIdentity as Identity)
from signaling.report_finalization import FinalizationError


class OperationsFixture(TransactionTestCase):
    reservation_permissions = ("view_signalingpoint", "generate_signaling_report", "finalize_technicalreport")
    acquire = core.PostgreSQLReservationConcurrencyTests.acquire
    submit = core.PostgreSQLReservationConcurrencyTests.submit
    def race(self, first, second):
        def safe(operation):
            def run():
                try:
                    return operation()
                except FinalizationError as error:
                    return error.code
            return run
        return core.PostgreSQLReservationConcurrencyTests.race(self, safe(first), safe(second))

    def setUp(self):
        core.PostgreSQLReservationConcurrencyTests.setUp(self)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        config = override_settings(REPORT_PRIVATE_ROOT=temporary.name, REPORT_ADMISSION_ENABLED=True,
            REPORT_SYSTEMD_SUPERVISION_ENABLED=True, REPORT_EXECUTOR_ENABLED=True,
            REPORT_EXECUTOR_RELEASE_ID=RELEASE, REPORT_EXECUTOR_SYSTEMD_USER="analise_app")
        config.enable()
        self.addCleanup(config.disable)
        host = patch.object(runtime, "host_identity", return_value=HOST)
        host.start()
        self.addCleanup(host.stop)
        for module, name in ((runtime, "manager_properties"), (executor, "render_snapshot"),
                             (executor, "convert_docx_to_pdf")):
            forbidden = patch.object(module, name, side_effect=AssertionError("No external execution in contracts tests"))
            forbidden.start()
            self.addCleanup(forbidden.stop)
        WaypointReportDraft.objects.create(signaling_point=self.point, inspection_address="Synthetic street",
            inspection_date="2026-10-28", inspector_name="Inspector")
        self.grant = self.acquire()
        self.actor = uuid4()

    def admit(self, key=None):
        return admission.admit(point_id=self.point.pk, identity=self.identity, credentials=self.grant.credentials,
            user_id=self.client.session["_auth_user_id"], key=key or uuid4(), expected_revision=1,
            parameters=QueryDict(), analysis_state={"view_mode": "individual", "map_data": []})

    def move(self, target, generation=None, event_id=None):
        return UUID(service.transition_barrier(expected_generation=generation or service.barrier_status()["generation"],
            target=target, actor=self.actor, event_id=event_id or uuid4()))


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL")
class ReportLaunchPostgreSQLTests(OperationsFixture):
    def setUp(self):
        super().setUp()
        self.attempt = self.admit()
        self.identity = supervision.prepare(attempt_id=self.attempt.pk, expected_execution_id=self.attempt.execution_id)
        self.release = Release.objects.create(release_id=RELEASE, bundle_sha256="1"*64,
            manifest_sha256="2"*64, execution_contract=service.execution_contract(), approved_by=uuid4())

    def request(self):
        return service.request_launch(identity_id=self.identity.pk)

    def begin(self, launch, event_id=None):
        return service.begin_dispatch(launch_id=launch.pk, actor=self.actor, event_id=event_id or uuid4())

    def observe(self, launch, ticket, **kwargs):
        return service.observe_launch(launch_id=launch.pk, dispatch_id=ticket, actor=self.actor,
            event_id=kwargs.pop("event_id", uuid4()), invocation_id=kwargs.pop("invocation_id", uuid4()), **kwargs)

    def test_request_is_durable_idempotent_and_consumes_no_new_number(self):
        number = ReportAnnualCounter.objects.get().last_reserved
        launch = self.request()
        connection.close()
        self.assertEqual(self.request().pk, launch.pk)
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, number)
        self.assertEqual(Launch.objects.get().state, "REQUESTED")
        self.assertIsNone(Launch.objects.get().dispatch_id)

    def test_concurrent_requests_have_one_record(self):
        results = self.race(self.request, self.request)
        self.assertEqual(Launch.objects.count(), 1)
        self.assertTrue(any(isinstance(value, Launch) for value in results))

    def test_only_one_concurrent_dispatch_receives_ticket(self):
        launch = self.request()
        results = self.race(lambda: self.begin(launch), lambda: self.begin(launch))
        self.assertEqual(sum(isinstance(value, UUID) for value in results), 1)
        self.assertEqual(Launch.objects.get().state, "UNCERTAIN")
        self.assertEqual(Event.objects.filter(kind="DISPATCH_BEGIN").count(), 1)

    def test_replay_never_grants_second_start(self):
        launch, event = self.request(), uuid4()
        self.assertIsInstance(self.begin(launch, event), UUID)
        self.assertIsNone(self.begin(launch, event))
        with self.assertRaises(FinalizationError):
            self.begin(launch)

    def test_closed_barrier_preserves_known_request_but_denies_dispatch(self):
        launch = self.request()
        self.move("DRAINING")
        self.assertEqual(self.request().pk, launch.pk)
        with self.assertRaisesMessage(FinalizationError, "publication_maintenance"):
            self.begin(launch)
        self.assertEqual(Launch.objects.get().state, "REQUESTED")
        self.assertEqual(Event.objects.filter(kind="DISPATCH_BEGIN").count(), 0)

    def test_release_label_alone_is_insufficient(self):
        Attempt.objects.filter(pk=self.attempt.pk).update(execution_contract={})
        with self.assertRaisesMessage(FinalizationError, "launch_release_incompatible"):
            self.request()
        self.assertFalse(Launch.objects.exists())

    def test_missing_release_authorization_is_rejected(self):
        with patch.object(Release.objects, "filter", return_value=Release.objects.none()):
            with self.assertRaisesMessage(FinalizationError, "launch_release_incompatible"):
                self.request()

    def test_job_observation_does_not_claim_start_or_termination(self):
        launch, event = self.request(), uuid4()
        ticket = self.begin(launch)
        service.observe_launch(launch_id=launch.pk, dispatch_id=ticket, actor=self.actor,
            event_id=event, job_id=23)
        launch.refresh_from_db()
        self.assertEqual((launch.state, launch.job_id, launch.invocation_id), ("UNCERTAIN", 23, None))

    def test_bind_requires_dispatch_and_correlated_invocation_when_launch_exists(self):
        launch = self.request()
        context = supervision.LaunchContext(self.identity.pk,
            runtime.validate_runtime(self.identity, **observations(self.identity)))
        with self.assertRaisesMessage(FinalizationError, "launch_binding_invalid"):
            executor.claim(self.attempt.pk, supervision=context)
        ticket = self.begin(launch)
        self.observe(launch, ticket, invocation_id=context.runtime.invocation_id)
        claimed = executor.claim(self.attempt.pk, supervision=context)
        self.assertEqual(claimed.state, "PROCESSING")
        self.assertNotEqual(claimed.execution_id, self.attempt.execution_id)
        with transaction.atomic():
            with self.assertRaisesMessage(FinalizationError, "execution_superseded"):
                admission.assert_execution(self.attempt.pk, self.attempt.execution_id)

    def test_launch_request_races_barrier_closing(self):
        results = self.race(self.request, lambda: self.move("DRAINING"))
        self.assertLessEqual(Launch.objects.count(), 1)
        self.assertTrue(any(isinstance(value, (Launch, UUID)) for value in results))
        if service.barrier_status()["state"] == "OPEN":
            self.move("DRAINING")
        if Launch.objects.exists():
            with self.assertRaisesMessage(FinalizationError, "publication_maintenance"):
                self.begin(Launch.objects.get())
        else:
            with self.assertRaisesMessage(FinalizationError, "publication_maintenance"):
                self.request()

    def test_release_authorization_and_events_are_immutable(self):
        with self.assertRaises(ValidationError):
            self.release.save()
        with self.assertRaises(ValidationError):
            Release.objects.update(bundle_sha256="3"*64)
        with self.assertRaises(ValidationError):
            self.release.delete()

    def test_launch_database_constraints_reject_partial_state_and_duplicate(self):
        launch = self.request()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Launch.objects.filter(pk=launch.pk).update(state="UNCERTAIN")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Launch.objects.create(identity=self.identity, release=self.release,
                                  contract_sha256=launch.contract_sha256)

    def test_release_cannot_be_replaced_by_new_instance_with_same_key(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Release(release_id=RELEASE, bundle_sha256="9"*64, manifest_sha256="8"*64,
                execution_contract=service.execution_contract(), approved_by=uuid4()).save()

    def test_intermediate_failure_rolls_back_ticket_and_audit(self):
        launch = self.request()
        with patch.object(Launch, "save", side_effect=OperationalError("synthetic")):
            with self.assertRaises(OperationalError):
                self.begin(launch)
        self.assertIsNone(Launch.objects.get().dispatch_id)
        self.assertFalse(Event.objects.exists())
        self.assertIsInstance(self.begin(launch), UUID)

    def test_lost_dispatch_commit_ack_never_reissues_start_authorization(self):
        launch, event = self.request(), uuid4()
        original = admission.coordination

        @contextmanager
        def lost_ack(*args, **kwargs):
            with original(*args, **kwargs) as slot:
                yield slot
            raise OperationalError("synthetic lost acknowledgement after commit")

        with patch.object(admission, "coordination", lost_ack):
            with self.assertRaises(OperationalError):
                self.begin(launch, event)
        self.assertEqual(Launch.objects.get().state, "UNCERTAIN")
        self.assertIsNone(self.begin(launch, event))
        with self.assertRaises(FinalizationError):
            self.begin(launch)

    def test_request_failure_leaves_no_executable_request(self):
        with patch.object(Launch.objects, "create", side_effect=OperationalError("synthetic")):
            with self.assertRaises(OperationalError):
                self.request()
        self.assertFalse(Launch.objects.exists())
        self.assertEqual(Slot.objects.get().attempt_id, self.attempt.pk)

    def test_observation_idempotency_and_invocation_fencing(self):
        launch = self.request()
        ticket, invocation, event = self.begin(launch), uuid4(), uuid4()
        self.observe(launch, ticket, invocation_id=invocation, event_id=event, job_id=12)
        self.observe(launch, ticket, invocation_id=invocation, event_id=event, job_id=12)
        with self.assertRaises(FinalizationError):
            self.observe(launch, uuid4(), invocation_id=invocation)
        with self.assertRaises(FinalizationError):
            self.observe(launch, ticket)
        with self.assertRaises(FinalizationError):
            self.observe(launch, ticket, event_id=event, invocation_id=uuid4())
        self.assertEqual(Launch.objects.get().state, "CONFIRMED")

    def test_terminal_is_not_proof_and_never_releases_slot(self):
        launch = self.request()
        invocation, ticket = uuid4(), self.begin(launch)
        self.observe(launch, ticket, invocation_id=invocation, terminal_result="signal")
        self.assertEqual(Launch.objects.get().state, "TERMINAL_OBSERVED")
        self.assertEqual(Slot.objects.get().attempt_id, self.attempt.pk)
        self.move("DRAINING")
        with self.assertRaisesMessage(FinalizationError, "deployment_not_quiescent"):
            self.move("DEPLOYING")
        with self.assertRaises(FinalizationError):
            self.observe(launch, ticket, invocation_id=invocation, terminal_result="success")

    def test_empty_slot_and_finalized_attempt_are_not_enough_for_deploy(self):
        launch = self.request()
        ticket = self.begin(launch)
        self.observe(launch, ticket, terminal_result="success")
        # Synthetic metadata only: never generate or publish a document in this suite.
        Slot.objects.update(attempt=None, execution_id=None)
        Attempt.objects.filter(pk=self.attempt.pk).update(state="FINALIZED")
        self.move("DRAINING")
        with self.assertRaisesMessage(FinalizationError, "deployment_not_quiescent"):
            self.move("DEPLOYING")

    def test_close_races_dispatch_without_unsafe_deploy(self):
        launch = self.request()
        results = self.race(lambda: self.begin(launch), lambda: self.move("DRAINING"))
        self.assertTrue(any(isinstance(value, UUID) for value in results))
        if service.barrier_status()["state"] == "OPEN":
            self.move("DRAINING")
        with self.assertRaisesMessage(FinalizationError, "deployment_not_quiescent"):
            self.move("DEPLOYING")

    def test_diagnostic_observes_without_mutation(self):
        self.request()
        before = (Launch.objects.get().state, Event.objects.count(), Barrier.objects.count())
        result = diagnostics.diagnose(attempt_id=self.attempt.pk)
        self.assertEqual(result["operations"]["launches"][0]["state"], "REQUESTED")
        self.assertFalse(result["recovery"]["permitted"])
        self.assertEqual(before, (Launch.objects.get().state, Event.objects.count(), Barrier.objects.count()))

    def test_close_denies_new_prepare_and_claim_but_cancel_allows_continuity(self):
        snapshot, number, epoch = self.attempt.version.snapshot, self.attempt.version.report.official_number, self.attempt.execution_id
        self.move("DRAINING")
        with self.assertRaisesMessage(FinalizationError, "publication_maintenance"):
            supervision.prepare(attempt_id=self.attempt.pk, expected_execution_id=epoch)
        with self.assertRaisesMessage(FinalizationError, "publication_maintenance"):
            executor.claim(self.attempt.pk)
        self.move("OPEN")
        self.assertEqual(self.request().identity_id, self.identity.pk)
        self.attempt.refresh_from_db()
        self.assertEqual((self.attempt.version.snapshot, self.attempt.version.report.official_number,
                          self.attempt.execution_id), (snapshot, number, epoch))


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL")
class ReportBarrierPostgreSQLTests(OperationsFixture):
    def test_empty_deploy_cycle_and_idempotent_reopening(self):
        self.assertEqual(Barrier.objects.count(), 0)
        self.move("DRAINING")
        generation = self.move("DEPLOYING")
        connection.close()
        self.assertEqual(service.barrier_status()["state"], "DEPLOYING")
        event = uuid4()
        reopened = self.move("OPEN", generation, event)
        self.assertEqual(self.move("OPEN", generation, event), reopened)
        with self.assertRaisesMessage(FinalizationError, "deployment_generation_stale"):
            self.move("DRAINING", generation)

    def test_no_direct_open_to_deploy_and_audit_rolls_back(self):
        with self.assertRaisesMessage(FinalizationError, "deployment_transition_invalid"):
            self.move("DEPLOYING")
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(service.barrier_status()["state"], "OPEN")

    def test_admission_closed_consumes_no_number_and_replay_is_allowed(self):
        key = uuid4()
        attempt = self.admit(key)
        self.move("DRAINING")
        self.assertEqual(self.admit(key).pk, attempt.pk)
        with self.assertRaisesMessage(FinalizationError, "publication_maintenance"):
            self.admit()
        self.assertEqual(ReportAnnualCounter.objects.get().last_reserved, 1)

    def test_close_races_admission_and_deploy_cannot_overtake(self):
        results = self.race(self.admit, lambda: self.move("DRAINING"))
        if service.barrier_status()["state"] == "OPEN":
            self.move("DRAINING")
        if Attempt.objects.exists():
            with self.assertRaisesMessage(FinalizationError, "deployment_not_quiescent"):
                self.move("DEPLOYING")
        else:
            self.move("DEPLOYING")
        with self.assertRaises(FinalizationError):
            self.admit()
        self.assertTrue(any(isinstance(value, (UUID, Attempt)) for value in results))

    def test_concurrent_administrators_cannot_both_transition_generation(self):
        epoch = service.barrier_status()["generation"]
        results = self.race(lambda: self.move("DRAINING", epoch), lambda: self.move("DRAINING", epoch))
        self.assertEqual(sum(isinstance(value, UUID) for value in results), 1)
        self.assertEqual(Event.objects.count(), 1)

    def test_database_failure_during_reopen_preserves_closed_barrier(self):
        self.move("DRAINING")
        generation = self.move("DEPLOYING")
        with patch.object(Event.objects, "create", side_effect=OperationalError("synthetic")):
            with self.assertRaises(OperationalError):
                self.move("OPEN", generation)
        self.assertEqual(service.barrier_status()["state"], "DEPLOYING")
        self.assertEqual(service.barrier_status()["generation"], generation)

    def test_singleton_constraint_and_persisted_compatibility(self):
        self.admit()
        self.assertEqual(Attempt.objects.get().execution_contract, service.execution_contract())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Barrier.objects.create(pk=2)
