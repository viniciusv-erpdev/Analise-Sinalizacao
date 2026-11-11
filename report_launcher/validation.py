"""JSON-only persisted-input validator; deliberately independent of Django."""
import hashlib
import json
import re
from uuid import UUID
from .protocol import Rejected

CONTRACT = {"admission": 1, "snapshot": 1, "renderer": 1, "launcher": 1}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_envelope(envelope, release, host_id, boot_id):
    """Untrusted DB input is bounded by the DB adapter; never log it."""
    try:
        a, v, i, l, r, s = (envelope[name] for name in ("attempt", "version", "identity", "launch", "release", "slot"))
        snapshot = v["snapshot"]
        key = UUID(i["id"])
        if (a["state"] != "ADMITTED" or a["admitted_at"] is None or a["deadline"] is not None
                or i["attempt_id"] != a["id"] or i["attempt_reference"] != a["id"] or i["bound_at"] is not None
                or i["expected_execution_id"] != a["execution_id"] or i["execution_id"] == a["execution_id"]
                or s["attempt_id"] != a["id"] or s["execution_id"] != a["execution_id"]
                or l["state"] != "REQUESTED" or l["dispatch_id"] is not None
                or l["identity_id"] != i["id"] or i["unit_name"] != f"rtsv-report-{key.hex}.service"
                or i["host_id"] != host_id or i["boot_id"] != str(boot_id)
                or i["service_user"] != "analise_app" or i["release_root"] != release["root"]
                or i["release_id"] != release["release_id"] or l["release_id"] != release["release_id"]
                or r["release_id"] != release["release_id"]
                or r["bundle_sha256"] != release["bundle_sha256"]
                or r["manifest_sha256"] != release["manifest_sha256"]
                or a["execution_contract"] != CONTRACT or r["execution_contract"] != CONTRACT
                or l["contract_sha256"] != digest(CONTRACT)
                or not isinstance(snapshot, dict) or len(canonical(snapshot)) > 8*1024*1024
                or digest(snapshot) != v["snapshot_sha256"]
                or digest(snapshot.get("source")) != v["source_sha256"]
                or snapshot.get("schema_version") != v["schema_version"] or v["schema_version"] != CONTRACT["snapshot"]
                or snapshot.get("author") != v["author_identity"]
                or snapshot.get("official_number") != envelope["official_number"]
                or v["finalized_at"] is not None or envelope["number_assigned_at"] is not None
                or envelope["derivatives"] or envelope["other_unfinished"]
                or envelope["identity_count"] != 1 or envelope["launch_count"] != 1):
            raise Rejected("intention_invalid")
        photos = envelope["photos"]
        if len(photos) > 10 or [p["metadata"] for p in photos] != snapshot["photos"]:
            raise Rejected("inputs_incomplete")
        for ordinal, photo in enumerate(photos):
            meta = photo["metadata"]
            if (photo["ordinal"] != ordinal or meta["ordinal"] != ordinal
                    or photo["size"] <= 0 or photo["size"] != meta["size"]
                    or photo["sha256"] != meta["sha256"] or not re.fullmatch(r"[a-f0-9]{64}", photo["sha256"])
                    or photo["content_type"] != meta["content_type"]):
                raise Rejected("inputs_incomplete")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        raise Rejected("intention_invalid") from None
    return i["unit_name"], str(key)
