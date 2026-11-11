"""Reusable official report data without a TestCase lifecycle."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from signaling.models import TechnicalReport, TechnicalReportVersion, ReportFinalizationAttempt as Attempt, SignalingPoint


def setup_report_data(self):
    self.reader = get_user_model().objects.create_user(username="reader")
    self.reader.user_permissions.add(Permission.objects.get(codename="view_official_reports"))
    self.owner = get_user_model().objects.create_user(username="original-owner")
    self.point = SignalingPoint.objects.create(latitude=0, longitude=0, status="OK")
    self.instant = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    self.report = self.make_report(1)
    self.url = reverse("signaling:report-library")
    self.client.force_login(self.reader)


class ReportDataMixin:
    def make_report(self, sequence, *, year=2026, issued=None, author="Autora Historica", waypoint=None, published=True):
        report = TechnicalReport.objects.create(year=year, sequence=sequence, waypoint=self.point,
            waypoint_history={"id": waypoint or self.point.pk}, number_reserved_at=self.instant,
            number_assigned_at=self.instant if published else None)
        self.make_version(report, 1, issued=issued, author=author)
        return report

    def make_version(self, report, number, *, state="FINALIZED", issued=None, author="Autora Historica", username="archived-user"):
        version = TechnicalReportVersion.objects.create(report=report, version=number, author=self.owner,
            author_identity={"username":username, "full_name":author},
            issued_at=issued or self.instant, finalized_at=self.instant if state == "FINALIZED" else None,
            snapshot={"secret":"DO-NOT-EXPOSE-SNAPSHOT /private/archive token"}, snapshot_sha256="0"*64, source_sha256="0"*64)
        Attempt.objects.create(version=version, requested_by=self.owner, idempotency_key=uuid4(),
            request_sha256="0"*64, state=state, deadline=self.instant+timedelta(minutes=15))
        return version

