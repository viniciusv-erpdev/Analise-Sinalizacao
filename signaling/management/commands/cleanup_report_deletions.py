"""Read-only unless --apply; only processes committed deletion outboxes."""
from django.core.management.base import BaseCommand
from signaling.models import ReportDeletion
from signaling.report_deletion import cleanup_deletion, ReportDeletionError


class Command(BaseCommand):
    help = "Inspect or resume private cleanup for explicitly deleted reports."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--operation", type=str)

    def handle(self, *args, **options):
        pending = ReportDeletion.objects.exclude(cleanup_state=ReportDeletion.State.COMPLETE)
        if options["operation"]:
            pending = pending.filter(pk=options["operation"])
        self.stdout.write(f"Pending deletion operations: {pending.count()}")
        if options["apply"]:
            for operation_id in list(pending.values_list("pk", flat=True)):
                try:
                    result = cleanup_deletion(operation_id=operation_id)
                    self.stdout.write(f"{operation_id}: {result.cleanup_state}")
                except ReportDeletionError as error:
                    self.stdout.write(f"{operation_id}: {error.code}")
        else:
            self.stdout.write("Read-only. --apply is required to remove private files.")
