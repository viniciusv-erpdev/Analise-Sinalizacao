"""One request -> at most one StartTransientUnit attempt. No recovery."""
import json
from pathlib import Path
import re
from uuid import UUID
from .protocol import Rejected
from .catalog import POLICY_SHA256, unit_properties
from .validation import validate_envelope, digest


def host_identity():
    try:
        host = Path("/etc/machine-id").read_text().strip()
        boot = UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip())
        if not re.fullmatch(r"[a-f0-9]{32}", host) or int(host, 16) == 0 or boot.int == 0:
            raise ValueError
        return host, boot
    except (OSError, ValueError):
        raise Rejected("host_unavailable") from None


def audit(code, peer, request=None):
    # Called with fixed codes and already validated IDs only. No raw exceptions.
    record = {"event": code, "peer_uid": peer["uid"]}
    if request is not None:
        record.update(request_id=request["request_id"], launch_id=request["launch_id"])
    print(json.dumps(record, sort_keys=True), flush=True)


class Launcher:
    def __init__(self, database, catalog, manager, host_reader=host_identity, audit_writer=audit):
        self.database, self.catalog, self.manager = database, catalog, manager
        self.host_reader, self.audit = host_reader, audit_writer

    def handle(self, request, peer):
        if peer["uid"] != self.catalog.dispatcher_uid or peer["uid"] <= 0:
            raise Rejected("peer_forbidden")
        status = self.database.status(request["launch_id"])
        if status is None:
            raise Rejected("launch_unknown")
        if request["operation"] == "status":
            return {"code": "STATUS", "state": status["state"], "consumed": status["consumed"]}
        if status["consumed"] or status["state"] != "REQUESTED":
            self.audit("start_not_reissued", peer, request)
            return {"code": "ALREADY_CONSUMED" if status["consumed"] else "UNCERTAIN", "state": status["state"]}
        envelope = self.database.envelope(request["launch_id"])
        release = self.catalog.validate(envelope["identity"]["release_id"])
        host, boot = self.host_reader()
        unit, identity = validate_envelope(envelope, release, host, boot)
        properties = unit_properties(release, identity)
        self.manager.preflight(unit, properties)  # Serialization only; no manager I/O.
        # All expensive validation precedes this short transactional compare/CAS.
        policy = digest({"profile": POLICY_SHA256, "properties": properties})
        receipt = self.database.consume(request, peer, host, boot, policy, envelope)
        if not receipt or not receipt["fresh"]:
            self.audit("start_not_reissued", peer, request)
            return {"code": "ALREADY_CONSUMED", "state": "UNCERTAIN"}
        self.audit("start_consumed", peer, request)
        try:
            job_id = self.manager.start(unit, properties)
            self.database.record_job(request["launch_id"], request["request_id"], job_id)
        except Exception:
            # Includes timeout, existing unit, DB ACK loss and process errors.
            # The receipt is burned. Never call start again, remove files or reset.
            self.audit("start_uncertain", peer, request)
            return {"code": "UNCERTAIN", "state": "UNCERTAIN"}
        self.audit("job_observed", peer, request)
        # A returned job is not a confirmed invocation or proof of termination.
        return {"code": "JOB_OBSERVED", "state": "UNCERTAIN", "job_id": job_id}
