from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client

WAYPOINT_PERMISSIONS = (
    "view_signalingpoint", "add_signalingpoint", "change_signalingpoint",
    "delete_signalingpoint", "generate_signaling_report",
)


def authorize(client, permissions=WAYPOINT_PERMISSIONS):
    user = get_user_model().objects.create_user(
        username=f"test-user-{get_user_model().objects.count()}",
    )
    user.user_permissions.set(Permission.objects.filter(
        content_type__app_label="signaling", codename__in=permissions,
    ))
    client.force_login(user)
    return user


def authorized_client(permissions=WAYPOINT_PERMISSIONS):
    client = Client()
    authorize(client, permissions)
    return client


class ReservationClient(Client):
    """Functional fixture: explicitly supplies an acquisition to legacy HTTP scenarios.

    Negative authorization/reservation tests continue using the ordinary Client.
    """
    def reserve(self, point_id):
        from uuid import uuid4
        from signaling import reservations as r
        if not hasattr(self, "_proofs"):
            self._proofs = {}
        actor_key = self.session.session_key
        key = (point_id, actor_key)
        if key not in self._proofs:
            grant = r.acquire_reservation(point_id=point_id,
                identity=r.ReservationIdentity(actor_key), interaction_id=uuid4())
            self._proofs[key] = grant.credentials
        proof = self._proofs[key]
        return {
            "HTTP_X_WAYPOINT_TOKEN": proof.token,
            "HTTP_X_WAYPOINT_INTERACTION": str(proof.interaction_id),
            "HTTP_X_WAYPOINT_GENERATION": str(proof.generation),
        }

    def release(self, point_id):
        from signaling import reservations as r
        key = (point_id, self.session.session_key)
        proof = self._proofs.pop(key)
        r.release_reservation(point_id=point_id,
            identity=r.ReservationIdentity(self.session.session_key), credentials=proof)

    def request(self, **request):
        import re
        from uuid import uuid4
        from signaling import reservations as r
        path = request.get("PATH_INFO", "")
        match = re.match(r"^/signaling/points/(\d+)/(.*)", path)
        if match:
            tail = match[2]
            protected = (tail in ("report/", "pgts/") or (
                request.get("REQUEST_METHOD") == "POST" and not tail.startswith("reservation/")
            ))
            if protected and not request.get("HTTP_X_WAYPOINT_TOKEN"):
                try:
                    request.update(self.reserve(int(match[1])))
                except r.ReservationError:
                    # Let the endpoint itself return its real auth/404/conflict.
                    request.update({
                        "HTTP_X_WAYPOINT_TOKEN": "a" * 43,
                        "HTTP_X_WAYPOINT_INTERACTION": str(uuid4()),
                        "HTTP_X_WAYPOINT_GENERATION": "1",
                    })
        return super().request(**request)


class ReservationFunctionalTestMixin:
    client_class = ReservationClient

    def setUp(self):
        from django.db import connection
        from unittest.mock import patch
        if connection.vendor == "sqlite":
            # Unit-level functional compatibility ONLY; real locking tests require PG.
            guard = patch("signaling.reservations._require_locking_backend")
            guard.start()
            self.addCleanup(guard.stop)
        super().setUp()
