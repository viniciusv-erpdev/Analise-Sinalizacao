"""Bounded wire format and per-packet Linux credentials. Standard library only."""
import array
import json
import os
import socket
import struct
from uuid import UUID

MAX_PACKET = 4096


class Rejected(Exception):
    """Only constant public codes; never put raw inputs/exceptions here."""


def uuid_value(value):
    try:
        parsed = UUID(value)
        if str(parsed) != value or not parsed.int:
            raise ValueError
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise Rejected("invalid_identifier") from None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Rejected("duplicate_field")
        result[key] = value
    return result


def decode(packet):
    if not packet or len(packet) > MAX_PACKET:
        raise Rejected("packet_size")
    try:
        value = json.loads(packet.decode("utf-8"), object_pairs_hook=_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(Rejected("invalid_json")))
    except (ValueError, UnicodeError, RecursionError):
        raise Rejected("invalid_json") from None
    if not isinstance(value, dict) or type(value.get("protocol")) is not int or value["protocol"] != 1:
        raise Rejected("protocol_unsupported")
    operation = value.get("operation")
    allowed = {"protocol", "operation", "request_id", "launch_id"}
    if operation == "start":
        allowed.add("expected_barrier_generation")
    elif operation != "status":
        raise Rejected("operation_forbidden")
    if set(value) != allowed:
        raise Rejected("fields_forbidden")
    for name in ("request_id", "launch_id"):
        uuid_value(value[name])
    if operation == "start":
        # The implicit OPEN barrier intentionally uses UUID zero.
        try:
            generation = UUID(value["expected_barrier_generation"])
            if str(generation) != value["expected_barrier_generation"]:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise Rejected("invalid_generation") from None
    return value


def authenticate(ancillary, flags, expected_uid, on_credentials=None):
    credentials = []
    invalid = bool(flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC))
    for level, kind, payload in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            descriptors = array.array("i")
            descriptors.frombytes(payload[:len(payload) - len(payload) % descriptors.itemsize])
            for descriptor in descriptors:
                os.close(descriptor)
            invalid = True
        elif level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS and len(payload) == struct.calcsize("3i"):
            credentials.append(struct.unpack("3i", payload))
        else:
            invalid = True
    if invalid or len(credentials) != 1:
        raise Rejected("credentials_invalid")
    pid, uid, gid = credentials[0]
    if on_credentials is not None:
        on_credentials({"pid": pid, "uid": uid, "gid": gid})
    if pid <= 0 or uid != expected_uid or uid <= 0:
        raise Rejected("peer_forbidden")
    return {"pid": pid, "uid": uid, "gid": gid}


def receive(connection, expected_uid, on_credentials=None):
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    connection.settimeout(5)
    packet, ancillary, flags, _ = connection.recvmsg(MAX_PACKET,
        socket.CMSG_SPACE(struct.calcsize("3i")) + socket.CMSG_SPACE(256 * struct.calcsize("i")),
        socket.MSG_CMSG_CLOEXEC)
    peer = authenticate(ancillary, flags, expected_uid, on_credentials)
    return decode(packet), peer
