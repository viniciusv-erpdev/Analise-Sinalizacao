"""Persist launch intent only. No systemd start or privileged subprocess."""
import json
from uuid import UUID
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from signaling import report_supervision as supervision
from signaling.report_finalization import FinalizationError


class Command(BaseCommand):
    help = "Prepare one never-reused systemd identity; does not start a unit."

    def add_arguments(self, parser):
        parser.add_argument("--attempt-id", type=UUID, required=True)
        parser.add_argument("--expected-execution-id", type=UUID, required=True)

    def handle(self, *args, **options):
        try:
            identity = supervision.prepare(attempt_id=options["attempt_id"],
                expected_execution_id=options["expected_execution_id"])
        except FinalizationError as error:
            raise CommandError(error.code) from None
        except DatabaseError:
            raise CommandError("supervision_database_state_unknown") from None
        self.stdout.write(json.dumps({"identity_id": str(identity.pk), "attempt_id": str(identity.attempt_reference),
            "execution_id": str(identity.execution_id), "unit_name": identity.unit_name,
            "release_id": identity.release_id, "unit_started": False, "termination_proof": "unavailable"}))
