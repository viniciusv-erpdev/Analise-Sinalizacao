"""Portable policy contract; rerun on real PostgreSQL before approving 7A.

No files are created/read, no reservations are mocked, no finalization is run.
"""
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.db import connection
from django.db.migrations.operations.models import AlterModelOptions
from django.http import Http404
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from signaling import report_read_access as access
from signaling.models import (SignalingPoint, WaypointReportDraft, TechnicalReport,
    TechnicalReportVersion, ReportArtifact, ReportFinalizationAttempt as Attempt)


@override_settings(REPORT_FINALIZATION_ENABLED=False)
class OfficialReportReadAccessTests(TestCase):
    def setUp(self):
        self.owner = self.actor("owner", "view_signalingpoint", "generate_signaling_report", "finalize_technicalreport")
        self.reader = self.actor("reader", "view_official_reports")
        self.downloader = self.actor("downloader", "download_official_reports")
        self.both = self.actor("both", "view_official_reports", "download_official_reports")
        self.outsider = self.actor("outsider")
        self.point = SignalingPoint.objects.create(latitude=0, longitude=0, status="OK")
        self.draft = WaypointReportDraft.objects.create(signaling_point=self.point, technical_analysis="Mutable draft")
        now = timezone.now()
        self.report = TechnicalReport.objects.create(waypoint=self.point, waypoint_history={"id":self.point.pk},
            year=2026, sequence=1, number_reserved_at=now, number_assigned_at=now)
        self.published = self.version(1, "FINALIZED")
        self.pending = self.version(2, "PROCESSING")
        self.pdf = self.artifact(self.published, "PDF")
        self.docx = self.artifact(self.published, "DOCX")
        self.photo = self.artifact(self.published, "PHOTO")
        self.pending_pdf = self.artifact(self.pending, "PDF")

    def actor(self, username, *codes):
        actor = get_user_model().objects.create_user(username=username)
        actor.user_permissions.set(Permission.objects.filter(content_type__app_label="signaling", codename__in=codes))
        return actor

    def version(self, number, state, *, report=None, finalized=None):
        if finalized is None:
            finalized = state == "FINALIZED"
        version = TechnicalReportVersion.objects.create(report=report or self.report, version=number,
            snapshot={"form":{"technical_analysis":"Historical conclusion"}, "point_id":self.point.pk},
            snapshot_sha256="0"*64, source_sha256="0"*64, author=self.owner,
            author_identity={"username":self.owner.username}, issued_at=timezone.now(),
            finalized_at=timezone.now() if finalized else None)
        Attempt.objects.create(version=version, requested_by=self.owner, idempotency_key=uuid4(),
            request_sha256="0"*64, state=state, deadline=timezone.now()+timedelta(minutes=15))
        return version

    def artifact(self, version, kind):
        return ReportArtifact.objects.create(version=version, kind=kind, storage_key=f"synthetic/{uuid4()}",
            download_name="synthetic", content_type="application/octet-stream", size=1, sha256="0"*64)

    def test_anonymous_unprivileged_download_only_and_finalizer_cannot_read_published(self):
        for actor in (AnonymousUser(), self.outsider, self.downloader, self.owner):
            with self.subTest(actor=actor):
                self.assertEqual(access.official_reports_for(actor).count(), 0)
                self.assertFalse(access.official_versions_for(actor).exists())
                self.assertFalse(access.official_artifacts_for(actor).exists())
                with self.assertRaises(Http404):
                    access.get_official_report(actor, self.report.pk)
                with self.assertRaises(Http404):
                    access.get_official_version(actor, self.report.pk, 1)
                with self.assertRaises(Http404):
                    access.get_official_artifact(actor, self.report.pk, 1, self.pdf.pk)

    def test_view_only_reads_shared_report_but_not_artifacts(self):
        self.assertEqual(access.get_official_report(self.reader, self.report.pk), self.report)
        self.assertEqual(access.get_official_version(self.reader, self.report.pk, 1), self.published)
        self.assertFalse(self.reader.has_perm("signaling.view_signalingpoint"))
        self.assertFalse(access.official_artifacts_for(self.reader).exists())
        with self.assertRaises(Http404):
            access.get_official_artifact(self.reader, self.report.pk, 1, self.pdf.pk)

    def test_both_permissions_allow_only_published_artifact_metadata(self):
        self.assertEqual(access.official_artifacts_for(self.both).count(), 3)
        for artifact in (self.pdf, self.docx, self.photo):
            self.assertEqual(access.get_official_artifact(self.both, self.report.pk, 1, artifact.pk), artifact)
        with self.assertRaises(Http404):
            access.get_official_artifact(self.both, self.report.pk, 2, self.pending_pdf.pk)

    def test_versions_with_all_unpublished_states_are_excluded(self):
        for number, state in enumerate(("FAILED", "INTERRUPTED", "STORING"), 3):
            self.version(number, state)
        self.assertEqual(list(access.official_versions_for(self.reader)), [self.published])
        self.assertEqual(access.official_reports_for(self.reader).count(), 1)
        for version in range(2, 6):
            with self.assertRaises(Http404):
                access.get_official_version(self.reader, self.report.pk, version)

    def test_partial_publication_markers_do_not_expose_a_version(self):
        self.version(3, "FINALIZED", finalized=False)
        self.version(4, "FAILED", finalized=True)
        report = TechnicalReport.objects.create(year=2026, sequence=2, waypoint_history={}, number_reserved_at=timezone.now())
        hidden = self.version(1, "FINALIZED", report=report)
        self.artifact(hidden, "PDF")
        self.assertEqual(access.official_reports_for(self.reader).count(), 1)
        self.assertEqual(list(access.official_versions_for(self.reader)), [self.published])
        self.assertEqual(access.official_artifacts_for(self.both).count(), 3)
        with self.assertRaises(Http404):
            access.get_official_report(self.reader, report.pk)

    def test_multiple_published_versions_do_not_duplicate_report_counts(self):
        self.version(3, "FINALIZED")
        self.assertEqual(access.official_reports_for(self.reader).count(), 1)
        self.assertEqual(access.official_versions_for(self.reader).count(), 2)
        self.assertEqual(len(access.official_reports_for(self.reader).order_by("pk")[:10]), 1)

    def test_disabled_conversion_and_no_reservation_do_not_block_history(self):
        self.assertEqual(access.get_official_report(self.reader, self.report.pk), self.report)
        self.assertEqual(access.get_official_artifact(self.both, self.report.pk, 1, self.pdf.pk), self.pdf)
        from signaling.models import WaypointReservation
        self.assertFalse(WaypointReservation.objects.exists())

    def test_other_user_reservation_does_not_block_reading(self):
        # No acquisition or protocol simulation: a historical reservation row is
        # unrelated to the query policy, including when currently occupied.
        from signaling.models import WaypointReservation
        now = timezone.now()
        WaypointReservation.objects.create(signaling_point=self.point, user=self.outsider,
            session_digest="0"*64, token_digest="0"*64, interaction_id=uuid4(), generation=1,
            acquired_at=now, renewed_at=now, expires_at=now+timedelta(minutes=2))
        self.assertEqual(access.get_official_report(self.reader, self.report.pk), self.report)

    def test_historical_data_survives_deletion_of_waypoint_draft_and_original_user(self):
        point_id = self.point.pk
        self.point.delete()
        self.owner.delete()
        version = access.get_official_version(self.reader, self.report.pk, 1)
        report = access.get_official_report(self.reader, self.report.pk)
        self.assertIsNone(report.waypoint_id)
        self.assertIsNone(version.author_id)
        self.assertEqual(report.waypoint_history["id"], point_id)
        self.assertEqual(version.author_identity["username"], "owner")
        self.assertEqual(version.snapshot["form"]["technical_analysis"], "Historical conclusion")
        self.assertEqual(access.get_official_artifact(self.both, report.pk, 1, self.pdf.pk), self.pdf)
        self.assertFalse(access.own_finalization_attempts_for(self.outsider).exists())

    def test_pending_attempts_are_owner_only_with_existing_finalizer_permissions(self):
        attempt = self.pending.attempt
        self.assertEqual(access.get_own_finalization_attempt(self.owner, attempt.pk), attempt)
        other = self.actor("other-finalizer", "view_signalingpoint", "generate_signaling_report", "finalize_technicalreport")
        for actor in (AnonymousUser(), self.reader, self.both, other):
            with self.assertRaises(Http404):
                access.get_own_finalization_attempt(actor, attempt.pk)
        self.assertFalse(access.official_versions_for(self.owner).exists())

    def test_artifact_lookup_is_bound_to_both_report_and_version(self):
        with self.assertRaises(Http404):
            access.get_official_artifact(self.both, uuid4(), 1, self.pdf.pk)
        with self.assertRaises(Http404):
            access.get_official_artifact(self.both, self.report.pk, 2, self.pdf.pk)

    def test_missing_malformed_and_unauthorized_objects_all_raise_http404(self):
        for identifier in (uuid4(), "not-a-uuid"):
            with self.assertRaises(Http404):
                access.get_official_report(self.reader, identifier)
        with self.assertRaises(Http404):
            access.get_official_version(self.reader, self.report.pk, 999)

    def test_permission_revocation_ignores_cached_permissions(self):
        self.assertTrue(self.both.has_perm(access.DOWNLOAD_OFFICIAL_REPORTS))
        self.both.user_permissions.remove(Permission.objects.get(codename="download_official_reports"))
        self.assertTrue(self.both.has_perm(access.DOWNLOAD_OFFICIAL_REPORTS))  # old object cache
        with self.assertRaises(Http404):
            access.get_official_artifact(self.both, self.report.pk, 1, self.pdf.pk)
        self.assertEqual(access.get_official_report(self.both, self.report.pk), self.report)

    def test_inactive_deleted_and_staff_only_users_do_not_gain_read_access(self):
        get_user_model().objects.filter(pk=self.both.pk).update(is_active=False)
        self.assertFalse(access.official_reports_for(self.both).exists())
        staff = self.actor("staff")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.assertFalse(access.official_reports_for(staff).exists())
        reader_id = self.reader.pk
        get_user_model().objects.filter(pk=reader_id).delete()
        self.assertFalse(access.official_reports_for(self.reader).exists())

    def test_denied_queries_never_search_or_count_report_tables(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(access.official_reports_for(self.outsider).count(), 0)
            self.assertEqual(list(access.official_versions_for(self.outsider)[:5]), [])
            self.assertFalse(access.official_artifacts_for(self.downloader).exists())
        self.assertFalse(any('"signaling_technicalreport' in query["sql"].lower() for query in queries))

    def test_group_authorization_is_explicit_and_does_not_grant_download(self):
        group = Group.objects.create(name="Explicit readers")
        group.permissions.add(Permission.objects.get(codename="view_official_reports"))
        self.outsider.groups.add(group)
        self.assertEqual(access.get_official_report(self.outsider, self.report.pk), self.report)
        self.assertFalse(access.official_artifacts_for(self.outsider).exists())

    def test_registration_and_permission_migration_do_not_grant_to_analista(self):
        from accounts.services import register_analyst
        group = Group.objects.create(name="analista")
        user = get_user_model()(username="public-user")
        user.set_unusable_password()
        created = register_analyst(SimpleNamespace(save=lambda commit: user))
        self.assertFalse(created.has_perm(access.VIEW_OFFICIAL_REPORTS))
        self.assertFalse(created.has_perm(access.DOWNLOAD_OFFICIAL_REPORTS))
        self.assertFalse(group.permissions.exists())
        migration = import_module("signaling.migrations.0013_official_report_read_permissions").Migration
        self.assertEqual(len(migration.operations), 1)
        self.assertIsInstance(migration.operations[0], AlterModelOptions)
        codes = {code for code, _ in migration.operations[0].options["permissions"]}
        self.assertEqual(codes, {"finalize_technicalreport", "view_official_reports", "download_official_reports"})

    def test_read_queries_do_not_modify_history_attempts_or_drafts(self):
        before = list(Attempt.objects.values("pk", "state", "execution_id", "updated_at"))
        versions = list(TechnicalReportVersion.objects.values("pk", "finalized_at", "snapshot"))
        access.get_official_report(self.reader, self.report.pk)
        access.get_official_version(self.reader, self.report.pk, 1)
        access.get_official_artifact(self.both, self.report.pk, 1, self.pdf.pk)
        self.assertEqual(list(Attempt.objects.values("pk", "state", "execution_id", "updated_at")), before)
        self.assertEqual(list(TechnicalReportVersion.objects.values("pk", "finalized_at", "snapshot")), versions)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.revision, 1)
