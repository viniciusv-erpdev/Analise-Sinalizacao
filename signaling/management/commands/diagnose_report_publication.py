"""Privacy-filtered JSON diagnostics only: no repair, kill, unlock or takeover."""
import json
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from signaling.report_diagnostics import diagnose, DiagnosticError


class Command(BaseCommand):
    help = "Read-only PostgreSQL report slot/attempt/file diagnostic; never grants recovery permission."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--attempt-id", type=UUID, help="Optional attempt UUID; default: slot owner")
        parser.add_argument("--verify-files", action="store_true", help="Also verify file hashes in bounded memory")

    def handle(self, *args, **options):
        try:
            result = diagnose(attempt_id=options["attempt_id"], verify_files=options["verify_files"])
        except DiagnosticError as error:
            raise CommandError(error.code) from None
        except DatabaseError:
            raise CommandError("diagnostic_database_unavailable") from None
        self.stdout.write(json.dumps(result, ensure_ascii=True, indent=2))
