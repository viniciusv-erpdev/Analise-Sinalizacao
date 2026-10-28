"""Read-only by default. Never publish reports or delete finalized artifacts."""
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from signaling.models import ReportArtifact, ReportFinalizationAttempt as Attempt
from signaling.report_finalization import ACTIVE
from signaling.report_storage import PrivateReportStorage


class Command(BaseCommand):
    help = "Audit interrupted attempts/orphan files; mutations require explicit flags."

    def add_arguments(self, parser):
        parser.add_argument("--mark-interrupted", action="store_true")
        parser.add_argument("--delete-orphans", action="store_true")
        parser.add_argument("--grace-hours", type=int, default=24)

    def handle(self, *args, **options):
        if options["grace_hours"] < 1:
            raise CommandError("Orphan grace must be at least one hour")
        now = timezone.now()
        stale = Attempt.objects.filter(state__in=ACTIVE, deadline__lte=now)
        self.stdout.write(f"Overdue attempts: {stale.count()}")
        if options["mark_interrupted"]:
            with transaction.atomic():
                stale.update(state=Attempt.State.INTERRUPTED, error_code="execution_interrupted", updated_at=now)
        storage = PrivateReportStorage()
        referenced = set(ReportArtifact.objects.values_list("storage_key", flat=True))
        cutoff = (now - timedelta(hours=options["grace_hours"])).timestamp()
        orphan_count = 0
        for key in storage.keys():
            if key in referenced or storage.modified_at(key) >= cutoff:
                continue
            version_id, execution_id, _ = key.split("/")
            # A slow writer may have written bytes but not registered metadata yet.
            # Retain even overdue active runs until explicitly interrupted/retried.
            if Attempt.objects.filter(version_id=version_id, execution_id=execution_id,
                                      state__in=ACTIVE).exists():
                continue
            orphan_count += 1
            if options["delete_orphans"]:
                # Recheck references immediately before removing only aged, unreferenced files.
                if not ReportArtifact.objects.filter(storage_key=key).exists():
                    storage.delete(key)
        self.stdout.write(f"Aged unreferenced artifacts: {orphan_count}")
        self.stdout.write("No publication performed. Default mode is read-only.")
