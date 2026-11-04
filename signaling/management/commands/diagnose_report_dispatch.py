"""Single read-only dispatcher evaluation; there is no active mode."""
import json

from django.core.management.base import BaseCommand, CommandError
from signaling.report_dispatcher import evaluate, DispatchDiagnosticError


class Command(BaseCommand):
    help = "Evaluate the report slot in dry-run only; never authorizes or starts dispatch."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Explicit diagnostic mode (also the default)")

    def handle(self, *args, **options):
        try:
            result = evaluate()
        except DispatchDiagnosticError as error:
            self.stdout.write(json.dumps({"schema_version": 1, "mode": "dry-run", "outcome": "UNAVAILABLE",
                "eligible": False, "authorization_granted": False, "reasons": [str(error)]}))
            raise CommandError(str(error)) from None
        self.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True))
