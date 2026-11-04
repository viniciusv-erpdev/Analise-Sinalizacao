"""Read-only publication observations, never evidence of process termination.

No coordination/admission API is called: even an absent singleton stays absent.
Filesystem checks are outside short PostgreSQL READ ONLY snapshots, without row
locks. A second snapshot detects concurrent database changes, not process liveness.
"""
from itertools import islice
import stat
from types import SimpleNamespace

from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from django.utils import timezone

from signaling.models import ReportPublicationSlot, ReportFinalizationAttempt as Attempt, ReportArtifact, ReportExecutionIdentity
from signaling.report_deletion import _version_keys
from signaling.report_snapshots import digest
from signaling.report_storage import PrivateReportStorage, ArtifactStorageError
from signaling.models import ReportLaunch, ReportDeploymentBarrier

ARTIFACT_LIMIT = 256
NAMESPACE_LIMIT = 1024
UNOWNED_LIMIT = 20
ATTEMPT_FIELDS = (
    "id", "execution_id", "state", "created_at", "updated_at", "admitted_at", "deadline",
    "version_id", "version__version", "version__issued_at", "version__finalized_at",
    "version__snapshot", "version__snapshot_sha256", "version__source_sha256",
    "version__author_identity", "version__schema_version", "version__report_id",
    "version__report__year", "version__report__sequence",
    "version__report__number_reserved_at", "version__report__number_assigned_at",
)


class DiagnosticError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _metadata(attempt_id):
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SET LOCAL statement_timeout = '5s'")
        slot = ReportPublicationSlot.objects.filter(pk=1).values("attempt_id", "execution_id").first()
        owner_id = slot["attempt_id"] if slot else None
        owner = Attempt.objects.filter(pk=owner_id).values("id", "execution_id", "state", "admitted_at").first()
        target = attempt_id if attempt_id is not None else owner_id
        attempt = Attempt.objects.filter(pk=target).values(*ATTEMPT_FIELDS).first()
        if attempt_id is not None and attempt is None:
            raise DiagnosticError("diagnostic_attempt_not_found")
        artifacts = list(ReportArtifact.objects.filter(version_id=attempt["version_id"])
            .order_by("kind", "ordinal", "pk").values("id", "kind", "ordinal", "created_at",
                "size", "sha256", "metadata", "storage_key")[:ARTIFACT_LIMIT + 1]) if attempt else []
        unowned = Attempt.objects.filter(admitted_at__isnull=False).exclude(state=Attempt.State.FINALIZED)
        if owner_id:
            unowned = unowned.exclude(pk=owner_id)
        identities = list(ReportExecutionIdentity.objects.filter(attempt_reference=target)
            .order_by("prepared_at").values("id", "execution_id", "host_id", "boot_id", "unit_name", "invocation_id",
                "prepared_at", "bound_at", "main_pid", "process_start_ticks", "cgroup_inode", "release_id")[:20])
        barrier = ReportDeploymentBarrier.objects.filter(pk=1).values("state", "generation", "updated_at").first()
        launches = list(ReportLaunch.objects.filter(identity__attempt_reference=target).order_by("requested_at")
            .values("id", "identity_id", "state", "requested_at", "dispatch_started_at", "job_id",
                    "invocation_id", "confirmed_at", "terminal_observed_at")[:20])
        return {"slot": slot, "owner": owner, "attempt": attempt, "identities": identities,
                "barrier": barrier, "launches": launches,
                "global_launch_count": ReportLaunch.objects.count(),
                "global_identity_count": ReportExecutionIdentity.objects.count(),
                "artifacts": artifacts[:ARTIFACT_LIMIT], "artifacts_truncated": len(artifacts) > ARTIFACT_LIMIT,
                "unowned_count": unowned.count(), "unowned": list(unowned.order_by("created_at", "pk")
                    .values("id", "state", "execution_id")[:UNOWNED_LIMIT])}


def _iso(value):
    return value.isoformat() if value else None


def _file_check(storage, artifact, verify):
    try:
        path = storage._path(artifact["storage_key"])
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            return "not_regular_file"
        if info.st_size != artifact["size"]:
            return "size_mismatch"
        if verify:
            with storage.open_verified(SimpleNamespace(**artifact)):
                pass
            return "verified"
        return "size_ok_hash_not_checked"
    except FileNotFoundError:
        return "missing"
    except ArtifactStorageError:
        return "integrity_or_path_unavailable"
    except OSError:
        return "unavailable"


def diagnose(*, attempt_id=None, verify_files=False):
    """Return a privacy-filtered JSON-ready observation. Never release/recover.

    READ ONLY transactions additionally enforce the no-write contract in PostgreSQL.
    Output contains no request hashes, idempotency keys, personal fields or paths.
    """
    if connection.vendor != "postgresql":
        raise DiagnosticError("diagnostic_requires_postgresql")
    if connection.in_atomic_block:
        raise DiagnosticError("diagnostic_requires_autocommit")
    started = timezone.now()
    before = _metadata(attempt_id)
    slot, owner, attempt = before["slot"], before["owner"], before["attempt"]
    issues = []
    if slot and bool(slot["attempt_id"]) != bool(slot["execution_id"]):
        issues.append("slot_owner_pair_inconsistent")
    if slot and slot["attempt_id"]:
        if not owner:
            issues.append("slot_attempt_missing")
        else:
            if slot["execution_id"] != owner["execution_id"]:
                issues.append("slot_execution_mismatch")
            if owner["admitted_at"] is None:
                issues.append("slot_owner_not_admitted")
            if owner["state"] == Attempt.State.FINALIZED:
                issues.append("finalized_attempt_retains_slot")
    if before["unowned_count"]:
        issues.append("unfinished_admitted_attempt_without_slot")
    output = {
        "schema_version": 1, "observed_from": _iso(started),
        "slot": {"exists": slot is not None, "occupied": bool(slot and slot["attempt_id"]),
                 "attempt_id": str(slot["attempt_id"]) if slot and slot["attempt_id"] else None,
                 "execution_id": str(slot["execution_id"]) if slot and slot["execution_id"] else None,
                 "owner_state": owner["state"] if owner else None},
        "attempt": None, "artifacts": [], "issues": issues,
        "operations": {"barrier": {key: str(value) if value is not None else None
                         for key, value in (before["barrier"] or {"state": "OPEN"}).items()},
                       "launches": [{key: str(value) if value is not None else None
                                     for key, value in launch.items()} for launch in before["launches"]],
                       "unverified_launch_count": before["global_launch_count"],
                       "unverified_identity_count": before["global_identity_count"],
                       "termination_verification": "unavailable"},
        "operational_identities": [{key: (_iso(value) if key in ("prepared_at", "bound_at") else
            str(value) if key in ("id", "execution_id", "boot_id", "invocation_id") and value is not None else value)
            for key, value in identity.items()} for identity in before["identities"]],
        "unowned_unfinished_attempts": {"count": before["unowned_count"],
            "items": [{"id": str(a["id"]), "state": a["state"], "execution_id": str(a["execution_id"])}
                      for a in before["unowned"]], "truncated": before["unowned_count"] > UNOWNED_LIMIT},
        "recovery": {"permitted": False, "executor_liveness": "unknown",
                     "termination_proof": "unavailable", "code": "termination_proof_unavailable"},
        "filesystem": {"checked": False, "hashes_requested": verify_files,
                       "artifacts_truncated": before["artifacts_truncated"],
                       "unreferenced_files_in_version": None, "namespace_scan_truncated": False},
    }
    if attempt:
        version_number = f"RTSV-{attempt['version__report__year']:04d}-{attempt['version__report__sequence']:04d}"
        output["attempt"] = {
            "id": str(attempt["id"]), "execution_id": str(attempt["execution_id"]), "state": attempt["state"],
            "version_id": str(attempt["version_id"]), "version": attempt["version__version"],
            "report_id": str(attempt["version__report_id"]), "official_number": version_number,
            "dates": {name: _iso(attempt[field]) for name, field in {
                "created_at": "created_at", "updated_at": "updated_at", "admitted_at": "admitted_at",
                "deadline": "deadline", "issued_at": "version__issued_at", "finalized_at": "version__finalized_at",
                "number_reserved_at": "version__report__number_reserved_at",
                "number_assigned_at": "version__report__number_assigned_at"}.items()},
        }
        snapshot = attempt["version__snapshot"]
        valid = (isinstance(snapshot, dict) and digest(snapshot) == attempt["version__snapshot_sha256"]
            and digest(snapshot.get("source")) == attempt["version__source_sha256"]
            and snapshot.get("official_number") == version_number
            and snapshot.get("author") == attempt["version__author_identity"]
            and snapshot.get("schema_version") == attempt["version__schema_version"])
        if not valid:
            issues.append("snapshot_integrity_failed")
        finalized = attempt["state"] == Attempt.State.FINALIZED
        if (bool(attempt["version__finalized_at"]) != finalized
                or (finalized and not attempt["version__report__number_assigned_at"])):
            issues.append("publication_markers_inconsistent")
        derivatives = {(a["kind"], a["ordinal"]) for a in before["artifacts"] if a["kind"] != "PHOTO"}
        if finalized and derivatives != {("PDF", 0), ("DOCX", 0)}:
            issues.append("published_artifacts_incomplete")
        if attempt["state"] == Attempt.State.ADMITTED and derivatives:
            issues.append("admitted_has_derivative_artifacts")
        photos = snapshot.get("photos") if isinstance(snapshot, dict) else None
        recorded = [a for a in before["artifacts"] if a["kind"] == "PHOTO"]
        if (not isinstance(photos, list) or [a["metadata"] for a in recorded] != photos
                or any(not isinstance(a["metadata"], dict) or a["ordinal"] != i
                       or a["sha256"] != a["metadata"].get("sha256")
                       or a["size"] != a["metadata"].get("size") for i, a in enumerate(recorded))):
            issues.append("photo_manifest_inconsistent")
        if before["artifacts_truncated"]:
            issues.append("artifact_listing_truncated")
        try:
            storage = PrivateReportStorage()
        except ImproperlyConfigured:
            storage = None
            issues.append("private_storage_configuration_invalid")
        output["filesystem"]["checked"] = storage is not None
        for artifact in before["artifacts"]:
            status = _file_check(storage, artifact, verify_files) if storage else "not_checked"
            output["artifacts"].append({"id": str(artifact["id"]), "kind": artifact["kind"],
                "ordinal": artifact["ordinal"], "size": artifact["size"],
                "created_at": _iso(artifact["created_at"]), "file_check": status})
            if status not in ("size_ok_hash_not_checked", "verified", "not_checked"):
                issues.append("artifact_file_inconsistent")
        if storage and not before["artifacts_truncated"]:
            try:
                keys = list(islice(_version_keys(storage, [str(attempt["version_id"])]), NAMESPACE_LIMIT + 1))
                truncated = len(keys) > NAMESPACE_LIMIT
                output["filesystem"]["namespace_scan_truncated"] = truncated
                if not truncated:
                    referenced = {a["storage_key"] for a in before["artifacts"]}
                    count = sum(key not in referenced for key in keys)
                    output["filesystem"]["unreferenced_files_in_version"] = count
                    if count:
                        issues.append("unreferenced_files_observed_not_safe_to_delete")
            except (ArtifactStorageError, OSError, ValueError):
                issues.append("version_namespace_unavailable")
    # No database snapshot remains open during hashing or directory enumeration.
    # A deleted target is a concurrent change, not an authorization to recover.
    try:
        after = _metadata(attempt_id)
        changed = digest(before) != digest(after)
    except DiagnosticError as error:
        if error.code != "diagnostic_attempt_not_found":
            raise
        changed = True
    output["database_changed_during_observation"] = changed
    output["observed_until"] = _iso(timezone.now())
    output["issues"] = sorted(set(issues))
    return output
