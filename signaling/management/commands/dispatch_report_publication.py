"""Explicit one-shot active dispatch; future supervision may invoke repeatedly."""
import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from signaling.report_active_dispatcher import (DispatchDatabase, DispatchError, dispatch_once,
    require_dispatch_user, host_identity)


class Command(BaseCommand):
    help = "Dispatch the sole persisted admission once; no queue or recovery."
    requires_system_checks = []
    requires_migrations_checks = False

    def handle(self, *args, **options):
        if not settings.REPORT_DISPATCH_ENABLED:
            raise CommandError("dispatch_disabled")
        try:
            require_dispatch_user()
            db = DispatchDatabase(settings.REPORT_DISPATCH_DSN)
            db.verify_privileges()
            result = dispatch_once(db, release=settings.REPORT_EXECUTOR_RELEASE_ID,
                root=str(Path(settings.BASE_DIR).resolve()), host_reader=host_identity)
        except DispatchError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(json.dumps({"schema_version": 1, "mode": "active", **result}, sort_keys=True))
