"""Manual foreground one-shot worker, deliberately without polling/takeover."""
from contextlib import contextmanager
import signal
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from signaling import report_executor


@contextmanager
def termination_signals():
    previous = {}
    def interrupt(signum, frame):
        # Let converter cleanup finish even if the operator sends another signal.
        for candidate in previous:
            signal.signal(candidate, signal.SIG_IGN)
        raise report_executor.ExecutorInterrupted()
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, interrupt)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


class Command(BaseCommand):
    help = "Execute one persistently admitted report; never retry or reclaim an interrupted execution."
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("--attempt-id", type=UUID, help="Optional admitted attempt UUID; default: global slot owner")

    def handle(self, *args, **options):
        try:
            with termination_signals():
                attempt = report_executor.execute(options["attempt_id"])
        except report_executor.ExecutionError as error:
            raise CommandError(error.code) from None
        except (report_executor.ExecutorInterrupted, KeyboardInterrupt, SystemExit):
            # Interruption during claim/commit may not have an acknowledged owner.
            raise CommandError("execution_interrupted_state_unknown") from None
        if attempt is None:
            self.stdout.write("no_admitted_report")
        else:
            self.stdout.write(f"{attempt.state} {attempt.pk}")
