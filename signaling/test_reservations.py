"""SQLite contract tests mock locking ONLY; PostgreSQL runs the same contract with real locks."""
from dataclasses import asdict, replace
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from signaling.models import SignalingPoint, WaypointReservation
from signaling import reservations as r
from signaling.test_support import authorize


class ReservationContract:
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        clock = patch("signaling.reservations._database_now", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.user = authorize(self.client, ("view_signalingpoint",))
        self.identity = r.ReservationIdentity(self.client.session.session_key)
        self.interaction = uuid4()
        self.point = SignalingPoint.objects.create(latitude=0, longitude=0, status="OK")

    def acquire(self, **kwargs):
        return r.acquire_reservation(**{
            "point_id": self.point.pk, "identity": self.identity,
            "interaction_id": self.interaction, **kwargs,
        })

    def renew(self, grant, **kwargs):
        return r.renew_reservation(**{
            "point_id": self.point.pk, "identity": self.identity,
            "credentials": grant.credentials, **kwargs,
        })

    def release(self, grant, **kwargs):
        return r.release_reservation(**{
            "point_id": self.point.pk, "identity": self.identity,
            "credentials": grant.credentials, **kwargs,
        })

    def other_session(self):
        client = Client()
        client.force_login(self.user)
        return r.ReservationIdentity(client.session.session_key)

    def test_first_acquisition_persists_only_verifiers(self):
        grant = self.acquire()
        row = WaypointReservation.objects.get()
        self.assertEqual(grant.credentials.generation, 1)
        self.assertEqual(len(grant.credentials.token), 43)
        self.assertNotEqual(row.token_digest, grant.credentials.token)
        self.assertNotEqual(row.session_digest, self.identity.session_key)
        self.assertEqual(row.user, self.user)
        self.assertEqual(row.expires_at, self.now + timedelta(seconds=120))
        self.assertEqual(row.acquired_at, row.renewed_at)
        self.assertNotIn(grant.credentials.token, repr(grant))
        self.assertNotIn(self.identity.session_key, repr(self.identity))
        self.assertNotIn(row.token_digest, repr(row))
        self.assertNotIn(row.session_digest, str(row))

    def test_second_acquisition_never_implicitly_reuses_existing_acquisition(self):
        self.acquire()
        with self.assertRaises(r.ReservationOccupied):
            self.acquire()

    def test_other_user_session_and_interaction_cannot_acquire_active_point(self):
        self.acquire()
        other = Client()
        authorize(other, ("view_signalingpoint",))
        for kwargs in [
            {"identity": r.ReservationIdentity(other.session.session_key)},
            {"identity": self.other_session()},
            {"interaction_id": uuid4()},
        ]:
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(r.ReservationOccupied):
                self.acquire(**kwargs)
        self.assertEqual(WaypointReservation.objects.count(), 1)

    def test_renewal_updates_expiry_without_changing_generation_or_acquisition(self):
        grant = self.acquire()
        self.now += timedelta(seconds=30)
        renewed = self.renew(grant)
        row = WaypointReservation.objects.get()
        self.assertEqual(renewed.credentials, grant.credentials)
        self.assertEqual(row.renewed_at, self.now)
        self.assertEqual(row.acquired_at, self.now - timedelta(seconds=30))
        self.assertEqual(row.expires_at, self.now + timedelta(seconds=120))

    def test_wrong_credentials_cannot_renew_release_or_validate(self):
        grant = self.acquire()
        other = Client()
        authorize(other, ("view_signalingpoint",))
        variants = [
            {"identity": r.ReservationIdentity(other.session.session_key)},
            {"identity": self.other_session()},
            {"credentials": replace(grant.credentials, token="a" * 43)},
            {"credentials": replace(grant.credentials, interaction_id=uuid4())},
        ]
        for changes in variants:
            with self.subTest(changes=list(changes)):
                with self.assertRaises(r.ReservationCredentialsInvalid):
                    self.renew(grant, **changes)
                with self.assertRaises(r.ReservationCredentialsInvalid):
                    self.release(grant, **changes)
                with self.assertRaises(r.ReservationCredentialsInvalid):
                    with r.validate_reservation(**{
                        "point_id": self.point.pk, "identity": self.identity,
                        "credentials": grant.credentials, **changes,
                    }):
                        self.fail("invalid acquisition admitted")

    def test_stale_generation_rejected(self):
        grant = self.acquire()
        with self.assertRaises(r.ReservationGenerationStale):
            self.renew(grant, credentials=replace(grant.credentials, generation=2))

    def test_expired_reservation_cannot_renew_or_validate(self):
        grant = self.acquire()
        self.now = grant.expires_at  # Equality is already expired.
        with self.assertRaises(r.ReservationExpired):
            self.renew(grant)
        with self.assertRaises(r.ReservationExpired):
            with r.validate_reservation(point_id=self.point.pk, identity=self.identity,
                                        credentials=grant.credentials):
                self.fail("expired acquisition admitted")

    def test_new_acquisition_replaces_expired_generation(self):
        old = self.acquire()
        self.now = old.expires_at
        new = self.acquire(interaction_id=uuid4())
        self.assertEqual(new.credentials.generation, 2)
        self.assertNotEqual(new.credentials.token, old.credentials.token)
        with self.assertRaises(r.ReservationGenerationStale):
            self.renew(old)

    def test_release_and_proven_repeat_are_stable(self):
        grant = self.acquire()
        self.assertTrue(self.release(grant))
        released = WaypointReservation.objects.get().released_at
        self.now += timedelta(seconds=1)
        self.assertTrue(self.release(grant))
        self.assertEqual(WaypointReservation.objects.get().released_at, released)
        with self.assertRaises(r.ReservationInactive):
            self.renew(grant)

    def test_other_owner_cannot_repeat_a_release(self):
        grant = self.acquire()
        self.release(grant)
        with self.assertRaises(r.ReservationCredentialsInvalid):
            self.release(grant, identity=self.other_session())

    def test_release_reacquire_generation_is_monotonic(self):
        old = self.acquire()
        self.release(old)
        new = self.acquire()
        self.assertEqual(new.credentials.generation, old.credentials.generation + 1)
        with self.assertRaises(r.ReservationGenerationStale):
            self.release(old)
        with r.validate_reservation(point_id=self.point.pk, identity=self.identity,
                                    credentials=new.credentials):
            pass

    def test_deleted_reservation_row_cannot_reset_waypoint_generation(self):
        old = self.acquire()
        WaypointReservation.objects.filter(signaling_point=self.point).delete()
        new = self.acquire()
        self.assertEqual(new.credentials.generation, old.credentials.generation + 1)
        with self.assertRaises(r.ReservationGenerationStale):
            self.release(old)

    def test_owner_may_release_expired_reservation(self):
        grant = self.acquire()
        self.now = grant.expires_at
        self.assertTrue(self.release(grant))

    def test_waypoint_not_found(self):
        with self.assertRaises(r.ReservationWaypointNotFound):
            self.acquire(point_id=999999)

    def test_invalid_arguments_and_anonymous_identity(self):
        for changes in [{"point_id": True}, {"point_id": 0}, {"interaction_id": None},
                        {"interaction_id": "not-a-uuid"}, {"interaction_id": 123}]:
            with self.subTest(changes=changes), self.assertRaises(r.InvalidReservationArguments):
                self.acquire(**changes)
        for identity in [None, AnonymousUser(), r.ReservationIdentity("")]:
            with self.assertRaises(r.ReservationAuthenticationRequired):
                self.acquire(identity=identity)

    def test_untrusted_deleted_expired_or_tampered_session_is_rejected(self):
        with self.assertRaises(r.ReservationAuthenticationRequired):
            self.acquire(identity=r.ReservationIdentity("a" * 32))
        session = self.client.session
        session["_auth_user_hash"] = "forged"
        session.save()
        with self.assertRaises(r.ReservationAuthenticationRequired):
            self.acquire()
        self.client.force_login(self.user)
        self.identity = r.ReservationIdentity(self.client.session.session_key)
        from django.contrib.sessions.models import Session
        Session.objects.filter(session_key=self.identity.session_key).update(expire_date=self.now)
        with self.assertRaises(r.ReservationAuthenticationRequired):
            self.acquire()

    def test_revoked_permission_or_inactive_user_rejected(self):
        grant = self.acquire()
        self.user.user_permissions.clear()
        with self.assertRaises(r.ReservationPermissionDenied):
            self.renew(grant)
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(r.ReservationAuthenticationRequired):
            self.release(grant)

    def test_invalid_tokens_are_rejected_without_echoing_secrets(self):
        grant = self.acquire()
        for token in ["", "bad", "a"*44, "!"*43, None]:
            with self.subTest(token_length=len(token) if token else 0):
                with self.assertRaises(r.InvalidReservationArguments) as error:
                    self.renew(grant, credentials=replace(grant.credentials, token=token))
                self.assertEqual(str(error.exception), "invalid_reservation_arguments")

    def test_password_change_invalidates_acquisition_identity(self):
        grant = self.acquire()
        self.user.set_unusable_password()
        self.user.save()
        with self.assertRaises(r.ReservationAuthenticationRequired):
            self.renew(grant)

    def test_copied_bearer_credentials_with_same_session_are_not_unforgeable_tab_identity(self):
        grant = self.acquire()
        copied_identity = r.ReservationIdentity(self.identity.session_key)
        copied_credentials = replace(grant.credentials)
        self.assertEqual(self.renew(grant, identity=copied_identity,
                                   credentials=copied_credentials).credentials,
                         grant.credentials)

    def test_generation_overflow_fails_without_resetting_counter(self):
        SignalingPoint.objects.filter(pk=self.point.pk).update(
            reservation_generation=9223372036854775807,
        )
        with self.assertRaises(r.InvalidReservationArguments):
            self.acquire()
        self.assertFalse(WaypointReservation.objects.exists())

    def test_status_is_read_only_private_and_ownership_requires_full_proof(self):
        def status(identity=self.identity, credentials=None):
            return r.get_reservation_status(point_id=self.point.pk, identity=identity,
                                            credentials=credentials)
        self.assertEqual(status().state, "available")
        self.assertFalse(WaypointReservation.objects.exists())
        grant = self.acquire()
        before = list(WaypointReservation.objects.values())
        self.assertEqual(status().state, "reserved_other")
        self.assertEqual(status(credentials=grant.credentials).state, "reserved_self")
        self.assertEqual(status(self.other_session(), grant.credentials).state, "reserved_other")
        self.assertEqual(status(credentials=replace(grant.credentials, token="b"*43)).state,
                         "reserved_other")
        payload = asdict(status(credentials=grant.credentials))
        self.assertEqual(set(payload), {"point_id", "state", "generation", "expires_at"})
        for secret in [grant.credentials.token, self.identity.session_key,
                       before[0]["token_digest"], before[0]["session_digest"]]:
            self.assertNotIn(secret, str(payload))
        self.assertEqual(list(WaypointReservation.objects.values()), before)
        self.now = grant.expires_at
        self.assertEqual(status(credentials=grant.credentials).state, "available")

    def test_validation_scope_encloses_mutation_and_rollback(self):
        grant = self.acquire()
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with r.validate_reservation(point_id=self.point.pk, identity=self.identity,
                                        credentials=grant.credentials) as point:
                self.assertTrue(connection.in_atomic_block)
                point.status = "ABSENT"
                point.save(update_fields=["status"])
                raise RuntimeError("rollback")
        self.point.refresh_from_db()
        self.assertEqual(self.point.status, "OK")

    @override_settings(WAYPOINT_RESERVATION_TTL_SECONDS=240,
                       WAYPOINT_RESERVATION_RENEW_INTERVAL_SECONDS=40)
    def test_configured_ttl(self):
        self.assertEqual(self.acquire().expires_at, self.now + timedelta(seconds=240))

    @override_settings(WAYPOINT_RESERVATION_TTL_SECONDS=30,
                       WAYPOINT_RESERVATION_RENEW_INTERVAL_SECONDS=30)
    def test_invalid_timing_fails_before_writing(self):
        with self.assertRaises(ImproperlyConfigured):
            self.acquire()
        self.assertFalse(WaypointReservation.objects.exists())

    def test_model_validation_accepts_active_and_released_tombstones(self):
        grant = self.acquire()
        WaypointReservation.objects.get().full_clean()
        self.release(grant)
        WaypointReservation.objects.get().full_clean()
        self.user.delete()
        row = WaypointReservation.objects.get()
        self.assertIsNone(row.user_id)
        row.full_clean()

    def test_acquisition_failure_rolls_back_generation_and_row(self):
        with patch.object(WaypointReservation, "save", side_effect=RuntimeError("failure")):
            with self.assertRaisesRegex(RuntimeError, "failure"):
                self.acquire()
        self.point.refresh_from_db()
        self.assertEqual(self.point.reservation_generation, 0)
        self.assertFalse(WaypointReservation.objects.exists())

    def test_constraint_prevents_two_rows_for_one_waypoint(self):
        self.acquire()
        row = WaypointReservation.objects.get()
        row.pk = None
        with self.assertRaises(IntegrityError), transaction.atomic():
            row.save(force_insert=True)

    def test_constraints_reject_zero_generation_and_invalid_times(self):
        self.acquire()
        for changes in [{"generation": 0}, {"expires_at": self.now},
                        {"released_at": self.now - timedelta(seconds=1)}]:
            with self.subTest(changes=list(changes)):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    WaypointReservation.objects.update(**changes)


class ReservationContractUnitTests(ReservationContract, TestCase):
    def setUp(self):
        # ONLY unit tests bypass the guard. This does not test concurrency on SQLite.
        guard = patch("signaling.reservations._require_locking_backend")
        guard.start()
        self.addCleanup(guard.stop)
        super().setUp()


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL test database")
class PostgreSQLReservationContractTests(ReservationContract, TransactionTestCase):
    pass


@skipUnless(connection.vendor == "sqlite", "SQLite refusal contract")
class SQLiteReservationSafetyTests(TestCase):
    def test_locking_operations_fail_explicitly_without_writes(self):
        authorize(self.client, ("view_signalingpoint",))
        identity = r.ReservationIdentity(self.client.session.session_key)
        point = SignalingPoint.objects.create(latitude=0, longitude=0, status="OK")
        credentials = r.ReservationCredentials(uuid4(), 1, "a" * 43)
        for operation in [r.renew_reservation, r.release_reservation]:
            with self.assertRaises(r.ReservationBackendUnsupported):
                operation(point_id=point.pk, identity=identity, credentials=credentials)
        with self.assertRaises(r.ReservationBackendUnsupported):
            r.acquire_reservation(point_id=point.pk, identity=identity, interaction_id=uuid4())
        with self.assertRaises(r.ReservationBackendUnsupported):
            with r.validate_reservation(point_id=point.pk, identity=identity, credentials=credentials):
                self.fail("SQLite must not authorize mutations")
        self.assertFalse(WaypointReservation.objects.exists())
        self.assertEqual(r.get_reservation_status(point_id=point.pk, identity=identity).state,
                         "available")
