"""Exclusive acquisitions, independent of HTTP. See docs/reference/waypoint-reservations.md."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import UUID

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, load_backend
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection, transaction
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.dateparse import parse_datetime

from signaling.authorization import VIEW
from signaling.models import SignalingPoint, WaypointReservation


class ReservationError(Exception):
    code = "reservation_error"

    def __init__(self):
        # Fixed messages never interpolate credentials or arguments.
        super().__init__(self.code)


class InvalidReservationArguments(ReservationError):
    code = "invalid_reservation_arguments"


class ReservationAuthenticationRequired(ReservationError):
    code = "authentication_required"


class ReservationPermissionDenied(ReservationError):
    code = "permission_denied"


class ReservationWaypointNotFound(ReservationError):
    code = "waypoint_not_found"


class ReservationOccupied(ReservationError):
    code = "reservation_occupied"


class ReservationCredentialsInvalid(ReservationError):
    code = "reservation_credentials_invalid"


class ReservationGenerationStale(ReservationError):
    code = "reservation_generation_stale"


class ReservationExpired(ReservationError):
    code = "reservation_expired"


class ReservationInactive(ReservationError):
    code = "reservation_inactive"


class ReservationBackendUnsupported(ReservationError):
    code = "reservation_backend_unsupported"


@dataclass(frozen=True)
class ReservationIdentity:
    """Server-side Django session key, not a client-declared user ID.

    Pass request.session.session_key in the future HTTP adapter. The service
    verifies the persisted authenticated session again after acquiring locks.
    """
    session_key: str = field(repr=False)


@dataclass(frozen=True)
class ReservationCredentials:
    interaction_id: UUID
    generation: int
    token: str = field(repr=False)


@dataclass(frozen=True)
class ReservationGrant:
    point_id: int
    credentials: ReservationCredentials
    expires_at: datetime


@dataclass(frozen=True)
class ReservationStatus:
    point_id: int
    state: str  # available, reserved_self, reserved_other
    generation: int
    expires_at: datetime | None = None


def reservation_timing():
    ttl = settings.WAYPOINT_RESERVATION_TTL_SECONDS
    interval = settings.WAYPOINT_RESERVATION_RENEW_INTERVAL_SECONDS
    if (type(ttl) is not int or type(interval) is not int
            or not 0 < interval < ttl):
        raise ImproperlyConfigured("Reservation timing requires integers: 0 < interval < TTL.")
    return timedelta(seconds=ttl), interval


def _require_locking_backend():
    if not settings.USE_TZ:
        raise ImproperlyConfigured("Reservation services require USE_TZ=True.")
    if connection.vendor != "postgresql" or not connection.features.has_select_for_update:
        raise ReservationBackendUnsupported()


def _database_now():
    """Called in a NEW statement AFTER all required locks have been obtained."""
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("SELECT clock_timestamp()")
            return cursor.fetchone()[0]
        if connection.vendor == "sqlite":
            # Read-only status and isolated unit tests; NEVER a locking fallback.
            cursor.execute("SELECT STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW')")
            return parse_datetime(cursor.fetchone()[0]).replace(tzinfo=timezone.utc)
    raise ReservationBackendUnsupported()


def _check_inputs(point_id, identity, interaction_id=None, credentials=None):
    if type(point_id) is not int or not 0 < point_id <= 9223372036854775807:
        raise InvalidReservationArguments()
    if (not isinstance(identity, ReservationIdentity)
            or not isinstance(identity.session_key, str)
            or not 1 <= len(identity.session_key) <= 40):
        raise ReservationAuthenticationRequired()
    if interaction_id is not None:
        if not isinstance(interaction_id, UUID) or interaction_id.version != 4:
            raise InvalidReservationArguments()
    if credentials is not None:
        if (not isinstance(credentials, ReservationCredentials)
                or not isinstance(credentials.interaction_id, UUID)
                or credentials.interaction_id.version != 4
                or type(credentials.generation) is not int
                or not 0 < credentials.generation <= 9223372036854775807
                or not isinstance(credentials.token, str)
                or len(credentials.token) != 43
                or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                       for c in credentials.token)):
            raise InvalidReservationArguments()


def _authenticated_user(identity, now):
    if settings.SESSION_ENGINE != "django.contrib.sessions.backends.db":
        raise ImproperlyConfigured("Reservation identities currently require database sessions.")
    session = Session.objects.filter(
        session_key=identity.session_key, expire_date__gt=now,
    ).first()
    if session is None:
        raise ReservationAuthenticationRequired()
    data = session.get_decoded()
    backend_path = data.get(BACKEND_SESSION_KEY)
    if backend_path not in settings.AUTHENTICATION_BACKENDS:
        raise ReservationAuthenticationRequired()
    try:
        user_pk = get_user_model()._meta.pk.to_python(data.get(SESSION_KEY))
        user = load_backend(backend_path).get_user(user_pk)
    except (ValueError, TypeError, ValidationError):
        raise ReservationAuthenticationRequired() from None
    if user is None or not user.is_authenticated or not user.is_active:
        raise ReservationAuthenticationRequired()
    auth_hash = data.get(HASH_SESSION_KEY)
    if not isinstance(auth_hash, str) or not any(
        constant_time_compare(auth_hash, candidate)
        for candidate in (user.get_session_auth_hash(), *user.get_session_auth_fallback_hash())
    ):
        raise ReservationAuthenticationRequired()
    if not user.has_perm(VIEW):
        raise ReservationPermissionDenied()
    return user


def _session_digest(identity):
    return salted_hmac(
        "signaling.reservation.session", identity.session_key, algorithm="sha256",
    ).hexdigest()


def _token_digest(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _active(reservation, now):
    return (reservation is not None and reservation.released_at is None
            and reservation.expires_at > now)


@contextmanager
def _locked(point_id, identity):
    _require_locking_backend()
    _authenticated_user(identity, _database_now())
    with transaction.atomic():
        try:
            point = SignalingPoint.objects.select_for_update().get(pk=point_id)
        except SignalingPoint.DoesNotExist:
            raise ReservationWaypointNotFound() from None
        reservation = WaypointReservation.objects.select_for_update().filter(
            signaling_point_id=point_id,
        ).first()
        yield point, reservation, _database_now()


def _verify(point, reservation, user, identity, credentials):
    if reservation is None:
        raise ReservationInactive()
    if (credentials.generation != reservation.generation
            or credentials.generation != point.reservation_generation):
        raise ReservationGenerationStale()
    if (reservation.user_id != user.pk
            or not constant_time_compare(reservation.session_digest, _session_digest(identity))
            or reservation.interaction_id != credentials.interaction_id
            or not constant_time_compare(reservation.token_digest, _token_digest(credentials.token))):
        raise ReservationCredentialsInvalid()


def acquire_reservation(*, point_id, identity, interaction_id):
    _check_inputs(point_id, identity, interaction_id=interaction_id)
    if interaction_id is None:
        raise InvalidReservationArguments()
    ttl, _ = reservation_timing()
    with _locked(point_id, identity) as (point, reservation, now):
        user = _authenticated_user(identity, now)
        if _active(reservation, now):
            # No implicit reuse, including by the same user/session/interaction.
            raise ReservationOccupied()
        if point.reservation_generation == 9223372036854775807:
            raise InvalidReservationArguments()
        token = secrets.token_urlsafe(32)
        point.reservation_generation += 1
        point.save(update_fields=["reservation_generation"])
        if reservation is None:
            reservation = WaypointReservation(signaling_point=point)
        reservation.user = user
        reservation.session_digest = _session_digest(identity)
        reservation.interaction_id = interaction_id
        reservation.token_digest = _token_digest(token)
        reservation.generation = point.reservation_generation
        reservation.acquired_at = now
        reservation.renewed_at = now
        reservation.expires_at = now + ttl
        reservation.released_at = None
        reservation.save()
        return ReservationGrant(
            point_id, ReservationCredentials(interaction_id, reservation.generation, token),
            reservation.expires_at,
        )


def renew_reservation(*, point_id, identity, credentials):
    _check_inputs(point_id, identity, credentials=credentials)
    if credentials is None:
        raise InvalidReservationArguments()
    ttl, _ = reservation_timing()
    with _locked(point_id, identity) as (point, reservation, now):
        user = _authenticated_user(identity, now)
        _verify(point, reservation, user, identity, credentials)
        if reservation.released_at is not None:
            raise ReservationInactive()
        if reservation.expires_at <= now:
            raise ReservationExpired()
        reservation.renewed_at = now
        reservation.expires_at = now + ttl
        reservation.save(update_fields=["renewed_at", "expires_at"])
        return ReservationGrant(point_id, credentials, reservation.expires_at)


def release_reservation(*, point_id, identity, credentials):
    """Return True for release AND a proven repeat; expired owners may release."""
    _check_inputs(point_id, identity, credentials=credentials)
    if credentials is None:
        raise InvalidReservationArguments()
    with _locked(point_id, identity) as (point, reservation, now):
        user = _authenticated_user(identity, now)
        _verify(point, reservation, user, identity, credentials)
        if reservation.released_at is None:
            reservation.released_at = now
            reservation.save(update_fields=["released_at"])
        return True


@contextmanager
def validate_reservation(*, point_id, identity, credentials):
    """Use WITH: mutate yielded point/children INSIDE this scope.

    Locks remain held to the end of the outermost transaction. A successful
    operation is admitted at the post-lock clock check, even if TTL elapses
    while a short protected mutation finishes. Never perform network I/O here.
    """
    _check_inputs(point_id, identity, credentials=credentials)
    if credentials is None:
        raise InvalidReservationArguments()
    with _locked(point_id, identity) as (point, reservation, now):
        user = _authenticated_user(identity, now)
        _verify(point, reservation, user, identity, credentials)
        if reservation.released_at is not None:
            raise ReservationInactive()
        if reservation.expires_at <= now:
            raise ReservationExpired()
        yield point


def get_reservation_status(*, point_id, identity, credentials=None):
    """Advisory read; self requires full acquisition proof, never user equality."""
    _check_inputs(point_id, identity, credentials=credentials)
    # No lock, no write, no implicit acquisition. This is NOT authorization.
    _authenticated_user(identity, _database_now())
    try:
        point = SignalingPoint.objects.get(pk=point_id)
    except SignalingPoint.DoesNotExist:
        raise ReservationWaypointNotFound() from None
    reservation = WaypointReservation.objects.filter(signaling_point_id=point_id).first()
    now = _database_now()
    user = _authenticated_user(identity, now)
    if not _active(reservation, now):
        return ReservationStatus(point_id, "available", point.reservation_generation)
    state = "reserved_other"
    if credentials is not None:
        try:
            _verify(point, reservation, user, identity, credentials)
        except (ReservationCredentialsInvalid, ReservationGenerationStale):
            pass
        else:
            state = "reserved_self"
    return ReservationStatus(point_id, state, reservation.generation, reservation.expires_at)
