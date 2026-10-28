"""Read-only report scopes. No storage, reservation, conversion or feature gate.

Consumers must start from these querysets BEFORE filters/counts/pagination.
Object getters hide missing and unauthorized objects with the same Http404.
These are application query boundaries, not protection against arbitrary ORM/SQL.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef
from django.http import Http404

from signaling.authorization import VIEW, REPORT
from signaling.models import (TechnicalReport, TechnicalReportVersion, ReportArtifact,
                              ReportFinalizationAttempt)

VIEW_OFFICIAL_REPORTS = "signaling.view_official_reports"
DOWNLOAD_OFFICIAL_REPORTS = "signaling.download_official_reports"
FINALIZE = "signaling.finalize_technicalreport"


def _authorized(user, permissions):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return False
    # Do not trust permission/is_active caches carried by a long-lived caller.
    actor = get_user_model().objects.filter(pk=user.pk, is_active=True).first()
    return actor is not None and actor.has_perms(permissions)


def _published_versions():
    # File absence/corruption does not erase historical publication. Artifact
    # access is scoped below; actual integrity checks remain a storage concern.
    return TechnicalReportVersion.objects.filter(
        finalized_at__isnull=False, report__number_assigned_at__isnull=False,
        attempt__state=ReportFinalizationAttempt.State.FINALIZED,
    )


def can_view_official_reports(user):
    return _authorized(user, (VIEW_OFFICIAL_REPORTS,))


def official_reports_for(user):
    if not can_view_official_reports(user):
        return TechnicalReport.objects.none()
    return TechnicalReport.objects.filter(Exists(_published_versions().filter(report_id=OuterRef("pk"))))


def official_versions_for(user):
    if not can_view_official_reports(user):
        return TechnicalReportVersion.objects.none()
    return _published_versions()


def official_artifacts_for(user):
    # Even artifact metadata/path lookup requires BOTH permissions. This function
    # does not read bytes or implement a download operation.
    if not _authorized(user, (VIEW_OFFICIAL_REPORTS, DOWNLOAD_OFFICIAL_REPORTS)):
        return ReportArtifact.objects.none()
    return ReportArtifact.objects.filter(version_id__in=_published_versions().values("pk"))


def own_finalization_attempts_for(user):
    # Preserve the existing finalizer policy; viewing the shared library never
    # confers access to another person's failed/pending snapshots or attempts.
    if not _authorized(user, (VIEW, REPORT, FINALIZE)):
        return ReportFinalizationAttempt.objects.none()
    return ReportFinalizationAttempt.objects.filter(requested_by_id=user.pk)


def _get(queryset, **lookup):
    try:
        return queryset.get(**lookup)
    except (queryset.model.DoesNotExist, ValidationError, ValueError, TypeError):
        raise Http404("Report object not found") from None


def get_official_report(user, report_id):
    return _get(official_reports_for(user), pk=report_id)


def get_official_version(user, report_id, version):
    return _get(official_versions_for(user), report_id=report_id, version=version)


def get_official_artifact(user, report_id, version, artifact_id):
    return _get(official_artifacts_for(user), pk=artifact_id,
                version__report_id=report_id, version__version=version)


def get_own_finalization_attempt(user, attempt_id):
    return _get(own_finalization_attempts_for(user), pk=attempt_id)
