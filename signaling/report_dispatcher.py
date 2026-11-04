"""Read-only dispatch discovery. Never prepares, claims, launches or grants a ticket.

Two bounded REPEATABLE READ / READ ONLY observations detect visible changes.
No row/advisory locks: every result may already be obsolete when returned.
"""
from datetime import datetime
import re

from django.conf import settings
from django.db import connection, transaction, DatabaseError
from django.utils import timezone

from signaling.models import (ReportPublicationSlot as Slot, ReportFinalizationAttempt as Attempt,
    ReportExecutionIdentity as Identity, ReportLaunch as Launch, ReportReleaseAuthorization as Release,
    TechnicalReportVersion as Version, TechnicalReport as Report, ReportArtifact as Artifact)
from signaling.report_operations import barrier_status, execution_contract
from signaling.report_snapshots import digest, canonical, MAX_SNAPSHOT_BYTES
from signaling.forms import MAX_REPORT_PHOTOS


class DispatchDiagnosticError(Exception):
    pass


def _read():
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SET LOCAL statement_timeout = '5s'")
        barrier = barrier_status()
        slot = Slot.objects.filter(pk=1).values("attempt_id", "execution_id").first()
        owner = slot["attempt_id"] if slot else None
        attempt = Attempt.objects.filter(pk=owner).values("id", "execution_id", "state", "admitted_at",
            "deadline", "execution_contract", "version_id", "updated_at").first()
        version = Version.objects.filter(pk=attempt["version_id"]).values("id", "report_id", "snapshot",
            "schema_version", "snapshot_sha256", "source_sha256", "author_identity", "issued_at",
            "finalized_at").first() if attempt else None
        report = Report.objects.filter(pk=version["report_id"]).values("year", "sequence",
            "number_assigned_at").first() if version else None
        identities = list(Identity.objects.filter(attempt_reference=owner).order_by("pk").values()[:2]) if owner else []
        launches = list(Launch.objects.filter(identity__attempt_reference=owner).order_by("pk").values()[:2]) if owner else []
        release_id = identities[0]["release_id"] if identities else settings.REPORT_EXECUTOR_RELEASE_ID
        release = Release.objects.filter(pk=release_id).values().first() if release_id else None
        photos = list(Artifact.objects.filter(version_id=version["id"], kind="PHOTO").order_by("ordinal")
            .values("ordinal", "metadata", "size", "sha256", "content_type", "storage_key")[:MAX_REPORT_PHOTOS + 1]) if version else []
        derivatives = Artifact.objects.filter(version_id=version["id"], kind__in=("DOCX", "PDF")).exists() if version else False
        unfinished = Attempt.objects.exclude(state=Attempt.State.FINALIZED)
        if owner:
            unfinished = unfinished.exclude(pk=owner)
        return {"barrier": barrier, "slot": slot, "attempt": attempt, "version": version, "report": report,
            "identities": identities, "launches": launches, "release": release, "photos": photos,
            "derivatives": derivatives, "other_unfinished": unfinished.count(),
            "identity_count": Identity.objects.count(), "launch_count": Launch.objects.count()}


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _integrity(data):
    attempt, version, report = data["attempt"], data["version"], data["report"]
    if not version or not report:
        return ["publication_metadata_missing"]
    snapshot = version["snapshot"]
    try:
        number = f"RTSV-{report['year']:04d}-{report['sequence']:04d}"
        if (not isinstance(snapshot, dict) or len(canonical(snapshot)) > MAX_SNAPSHOT_BYTES
                or digest(snapshot) != version["snapshot_sha256"]
                or digest(snapshot.get("source")) != version["source_sha256"]
                or snapshot.get("official_number") != number
                or snapshot.get("author") != version["author_identity"]
                or snapshot.get("schema_version") != version["schema_version"]
                or datetime.fromisoformat(snapshot.get("issued_at", "")) != version["issued_at"]):
            return ["snapshot_integrity_failed"]
        photos = data["photos"]
        if (not isinstance(snapshot.get("photos"), list) or len(photos) > MAX_REPORT_PHOTOS
                or [photo["metadata"] for photo in photos] != snapshot["photos"]):
            return ["photo_metadata_incomplete"]
        for ordinal, photo in enumerate(photos):
            metadata = photo["metadata"]
            if (photo["ordinal"] != ordinal or metadata.get("ordinal") != ordinal
                    or type(photo["size"]) is not int or photo["size"] <= 0
                    or photo["size"] != metadata.get("size") or not _sha(photo["sha256"])
                    or photo["sha256"] != metadata.get("sha256")
                    or photo["content_type"] != metadata.get("content_type")
                    or not re.fullmatch(r"[a-f0-9-]{36}/[a-f0-9-]{36}/[a-f0-9-]{36}\.(jpg|png)", photo["storage_key"])
                    or photo["storage_key"].split("/")[0] != str(version["id"])):
                return ["photo_metadata_invalid"]
        if attempt["state"] == Attempt.State.ADMITTED and (
                data["derivatives"] or version["finalized_at"] or report["number_assigned_at"]):
            return ["admitted_attempt_has_results"]
    except (ValueError, TypeError, AttributeError, OverflowError):
        return ["snapshot_integrity_failed"]
    return []


def _classify(data):
    """Pure policy projection. It does NOT replace transactional operations."""
    attempt, slot = data["attempt"], data["slot"]
    identities, launches = data["identities"], data["launches"]
    identity = identities[0] if len(identities) == 1 else None
    launch = launches[0] if len(launches) == 1 else None
    issues = []
    if data["other_unfinished"]:
        issues.append("unfinished_attempt_outside_slot")
    if slot and bool(slot["attempt_id"]) != bool(slot["execution_id"]):
        issues.append("slot_owner_pair_invalid")
    if slot and slot["attempt_id"] and not attempt:
        issues.append("slot_attempt_missing")
    if attempt:
        if slot["execution_id"] != attempt["execution_id"]:
            issues.append("slot_execution_mismatch")
        if attempt["admitted_at"] is None:
            issues.append("slot_owner_not_admitted")
        if attempt["deadline"] is not None:
            issues.append("admitted_deadline_invalid")
        if attempt["state"] == Attempt.State.FINALIZED:
            issues.append("finalized_attempt_owns_slot")
        issues.extend(_integrity(data))
        if len(identities) > 1 or data["identity_count"] > len(identities):
            issues.append("unverified_other_identity")
        if len(launches) > 1 or data["launch_count"] > len(launches):
            issues.append("unverified_other_launch")
    if identity and attempt:
        bound = identity["bound_at"] is not None
        epoch = identity["execution_id"] if bound else identity["expected_execution_id"]
        if (identity["attempt_id"] != attempt["id"] or epoch != attempt["execution_id"]
                or identity["unit_name"] != f"rtsv-report-{identity['id'].hex}.service"
                or not re.fullmatch(r"[0-9a-f]{32}", identity["host_id"])
                or int(identity["host_id"], 16) == 0 or not identity["boot_id"].int
                or identity["execution_id"] == identity["expected_execution_id"]
                or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,63}", identity["service_user"])
                or identity["service_user"] == "root"
                or (bound and attempt["state"] == Attempt.State.ADMITTED)
                or (not bound and attempt["state"] in (Attempt.State.PROCESSING, Attempt.State.STORING))):
            issues.append("identity_metadata_invalid")
    if launch and identity and attempt:
        if (launch["identity_id"] != identity["id"] or launch["release_id"] != identity["release_id"]
                or launch["contract_sha256"] != digest(attempt["execution_contract"])
                or (launch["invocation_id"] and identity["invocation_id"]
                    and launch["invocation_id"] != identity["invocation_id"])
                or (identity["bound_at"] and launch["state"] == Launch.State.REQUESTED)):
            issues.append("launch_metadata_invalid")
    if issues:
        return "INCONSISTENT", issues
    if data["barrier"]["state"] != "OPEN":
        return "MAINTENANCE", ["publication_maintenance"]
    if not attempt:
        if data["identity_count"] or data["launch_count"]:
            return "UNCERTAIN", ["unverified_operational_history"]
        return "NO_ADMISSION", ["slot_empty"]
    if attempt["state"] in (Attempt.State.FAILED, Attempt.State.INTERRUPTED):
        return "UNCERTAIN", ["admission_reconciliation_required"]
    if launch and launch["state"] in (Launch.State.UNCERTAIN, Launch.State.TERMINAL_OBSERVED):
        return "UNCERTAIN", ["launch_uncertain" if launch["state"] == Launch.State.UNCERTAIN else "termination_unverified"]
    if attempt["state"] in (Attempt.State.PROCESSING, Attempt.State.STORING):
        return "EXECUTION_IN_PROGRESS", ["execution_already_started"]
    if attempt["state"] != Attempt.State.ADMITTED:
        return "INCONSISTENT", ["attempt_state_invalid"]
    release, contract = data["release"], attempt["execution_contract"]
    if (contract != execution_contract() or not release or release["execution_contract"] != contract
            or contract.get("snapshot") != data["version"]["schema_version"]
            or not re.fullmatch(r"[0-9a-f]{40,64}", release["release_id"])
            or not _sha(release["bundle_sha256"]) or not _sha(release["manifest_sha256"])):
        return "INCOMPATIBLE", ["launch_release_incompatible"]
    if identity and (identity["release_id"] != settings.REPORT_EXECUTOR_RELEASE_ID
            or identity["service_user"] != settings.REPORT_EXECUTOR_SYSTEMD_USER):
        return "INCOMPATIBLE", ["supervision_configuration_mismatch"]
    if launch:
        return "LAUNCH_REQUESTED", ["launch_already_requested"]
    if not identity:
        return "PREPARATION_REQUIRED", ["operational_identity_missing"]
    return "ELIGIBLE", ["persisted_metadata_eligible"]


def evaluate():
    """JSON-safe diagnostic of the slot owner only. Works with flags disabled."""
    if connection.vendor != "postgresql":
        raise DispatchDiagnosticError("dispatcher_requires_postgresql")
    if connection.in_atomic_block or not connection.get_autocommit():
        raise DispatchDiagnosticError("dispatcher_requires_autocommit")
    started = timezone.now()
    try:
        before = _read()
        observed_outcome, reasons = _classify(before)
        after = _read()
    except DatabaseError:
        raise DispatchDiagnosticError("dispatcher_database_unavailable") from None
    changed = before != after
    attempt = before["attempt"]
    identity = before["identities"][0] if len(before["identities"]) == 1 else None
    launch = before["launches"][0] if len(before["launches"]) == 1 else None
    return {"schema_version": 1, "mode": "dry-run", "outcome": "STALE" if changed else observed_outcome,
        "observed_outcome": observed_outcome, "reasons": reasons,
        "eligible": observed_outcome == "ELIGIBLE" and not changed,
        "authorization_granted": False, "potentially_stale": True,
        "database_changed_during_observation": changed,
        "observed_at": started.isoformat(), "completed_at": timezone.now().isoformat(),
        "barrier": {"state": before["barrier"]["state"], "generation": str(before["barrier"]["generation"])},
        "candidate": {"attempt_id": str(attempt["id"]), "state": attempt["state"],
            "execution_id": str(attempt["execution_id"]),
            "identity_id": str(identity["id"]) if identity else None,
            "launch_id": str(launch["id"]) if launch else None,
            "launch_state": launch["state"] if launch else None} if attempt else None,
        "activation_flags": {name: bool(getattr(settings, name)) for name in
            ("REPORT_ADMISSION_ENABLED", "REPORT_EXECUTOR_ENABLED", "REPORT_SYSTEMD_SUPERVISION_ENABLED")},
        "external_checks": {name: "not_verified" for name in
            ("systemd", "host_boot", "release_bundle", "release_manifest", "private_files", "termination")}}
