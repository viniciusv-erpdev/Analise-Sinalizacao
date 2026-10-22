"""Stateless content reconciliation: no timestamp cursor or reservation access."""
import hashlib
import json

from signaling.services import get_signaling_map_data


def waypoint_changes(known):
    current = {}
    upserts = []
    for point in get_signaling_map_data():
        digest = hashlib.sha256(json.dumps(
            point, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")).hexdigest()
        key = str(point["id"])
        current[key] = digest
        if known.get(key) != digest:
            upserts.append({"point": point, "revision": digest})
    return {"success": True, "upserts": upserts,
            "deleted": [int(key) for key in known if key not in current]}
