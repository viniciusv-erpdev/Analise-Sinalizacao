"""Entry point for a system-manager transient unit; no launcher or recovery."""
from uuid import UUID
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from signaling import report_executor, report_supervision
from signaling.management.commands.execute_admitted_report import termination_signals


class Command(BaseCommand):
    help = "Bind and execute a prepared identity inside its own verified systemd unit."

    def add_arguments(self, parser):
        parser.add_argument("--identity-id", type=UUID, required=True)

    def handle(self, *args, **options):
        try:
            with termination_signals():
                attempt_id, context = report_supervision.context(options["identity_id"])
                result = report_executor.execute(attempt_id, supervision=context)
        except report_executor.ExecutionError as error:
            raise CommandError(error.code) from None
        except DatabaseError:
            raise CommandError("supervision_database_state_unknown") from None
        except (report_executor.ExecutorInterrupted, KeyboardInterrupt, SystemExit):
            raise CommandError("execution_interrupted_state_unknown") from None
        self.stdout.write(f"{result.state} {result.pk}")
