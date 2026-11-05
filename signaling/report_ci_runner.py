"""CI runner for mandatory suites. A skipped required check is a failed job."""
from django.test.runner import DiscoverRunner
from django.db import connection

REQUIRED_LABELS = tuple("signaling." + name for name in (
    "test_report_async_postgresql", "test_report_active_dispatcher",
    "test_report_admission_postgresql", "test_report_operations_postgresql",
    "test_report_dispatcher_postgresql", "test_report_launcher_postgresql",
    "test_report_diagnostics_postgresql", "test_report_deletion_postgresql",
    "test_report_finalization_postgresql", "test_report_readiness",
    "test_report_permission_policy_postgresql", "test_report_release_linux",
)) + tuple("signaling.test_report_supervision_postgresql.SupervisionPostgreSQLTests." + name for name in (
    "test_prepare_persists_before_claim_and_replays_without_new_name",
    "test_concurrent_prepare_has_one_launch_intention",
    "test_claim_commits_runtime_and_fencing_together",
    "test_concurrent_binding_cannot_create_two_active_invocations",
    "test_manual_cannot_bypass_plan_even_after_flag_disabled",
    "test_binding_rollback_keeps_admission_and_unbound_identity",
    "test_boot_or_release_changes_never_reuse_plan",
    "test_context_is_verified_before_claim_and_used_identity_cannot_restart",
    "test_immutable_identity_and_database_unique_names",
    "test_diagnostic_displays_identity_but_never_termination_proof",
)) + tuple("signaling.test_report_executor_postgresql.ReportExecutorPostgreSQLTests." + name for name in (
    "test_two_executors_claim_using_distinct_connections_only_one_starts",
    "test_missing_slot_ownership_never_starts",
    "test_mismatched_execution_id_is_rejected",
    "test_generation_failure_retains_slot",
    "test_converter_timeout_retains_snapshot_number_and_slot",
    "test_keyboard_interruption_is_recoverable_but_not_automatically_retried",
    "test_command_sigterm_preserves_slot_and_restores_handler",
    "test_real_child_process_exit_after_claim_keeps_slot",
    "test_old_execution_cannot_commit_after_execution_id_changes",
    "test_database_connection_loss_keeps_ambiguous_execution",
    "test_executor_disabled_gate_does_not_claim",
    "test_execution_rejects_ambient_transaction",
))


class NoSkipRunner(DiscoverRunner):
    def build_suite(self, test_labels=None, **kwargs):
        if connection.vendor != "postgresql":
            raise RuntimeError("Mandatory report contracts require PostgreSQL")
        if list(test_labels or ()) == ["report-contracts"]:
            test_labels = REQUIRED_LABELS
            self.log("Mandatory contracts: real LibreOffice pipeline is a separate operational gate")
        return super().build_suite(test_labels, **kwargs)

    def suite_result(self, suite, result, **kwargs):
        failures = super().suite_result(suite, result, **kwargs)
        if result.testsRun == 0:
            self.log("ERROR: mandatory suite collected no tests")
            return failures + 1
        if result.skipped:
            self.log(f"ERROR: {len(result.skipped)} mandatory tests skipped")
        return failures + len(result.skipped)
