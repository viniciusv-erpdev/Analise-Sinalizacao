"""Read-only by default. Never publish reports or delete finalized artifacts."""
from datetime import timedelta
from contextlib import nullcontext
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, connection
from django.utils import timezone

from signaling.models import ReportArtifact, ReportFinalizationAttempt as Attempt, ReportPublicationSlot
from signaling.report_finalization import ACTIVE, FinalizationError
from signaling.report_admission import coordination
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
        # A deadline cannot prove an admitted executor is dead. Never change its
        # state or slot here; future supervised recovery must establish that fact.
        stale = Attempt.objects.filter(state__in=ACTIVE, deadline__lte=now, admitted_at__isnull=True)
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
            if ReportPublicationSlot.objects.filter(attempt__version_id=version_id).exists():
                continue
            # A slow writer may have written bytes but not registered metadata yet.
            # Retain even overdue active runs until explicitly interrupted/retried.
            if Attempt.objects.filter(version_id=version_id, execution_id=execution_id,
                                      state__in=ACTIVE).exists():
                continue
            orphan_count += 1
            if options["delete_orphans"]:
                try:
                    # Serialize with in-flight admission, whose rows may not yet
                    # be visible. No deletion on ambiguous admission commits.
                    with coordination() if connection.vendor == "postgresql" else nullcontext():
                        if (not ReportArtifact.objects.filter(storage_key=key).exists()
                                and not ReportPublicationSlot.objects.filter(attempt__version_id=version_id).exists()
                                and not Attempt.objects.filter(version_id=version_id,
                                    execution_id=execution_id, state__in=ACTIVE).exists()):
                            storage.delete(key)
                except FinalizationError as error:
                    if error.code != "publication_busy":
                        raise
        self.stdout.write(f"Aged unreferenced artifacts: {orphan_count}")
        self.stdout.write("No publication performed. Default mode is read-only.")
