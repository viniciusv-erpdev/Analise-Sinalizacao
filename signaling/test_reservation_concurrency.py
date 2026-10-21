"""REAL PostgreSQL connections. These tests never mock the backend guard or clock.

Barriers start contenders together. Waiting requests are confirmed through
pg_blocking_pids BEFORE the controlling transaction changes state. No timing
assumption based on sleep is used to establish ordering.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue
from threading import Barrier, Event
from time import monotonic
from unittest import skipUnless
from uuid import uuid4

from django.contrib.sessions.models import Session
from django.db import connection, connections, transaction
from django.test import TransactionTestCase

from signaling.models import SignalingPoint, WaypointReservation
from signaling import reservations as r
from signaling.test_support import authorize


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL test database")
class PostgreSQLReservationConcurrencyTests(TransactionTestCase):
    reservation_permissions = ("view_signalingpoint",)

    def setUp(self):
        authorize(self.client, self.reservation_permissions)
        self.identity = r.ReservationIdentity(self.client.session.session_key)
        self.point = SignalingPoint.objects.create(latitude=0, longitude=0, status="OK")
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.executor.shutdown, wait=True, cancel_futures=True)

    def acquire(self):
        return r.acquire_reservation(point_id=self.point.pk, identity=self.identity,
                                     interaction_id=uuid4())

    def renew(self, grant):
        return r.renew_reservation(point_id=self.point.pk, identity=self.identity,
                                   credentials=grant.credentials)

    def release(self, grant):
        return r.release_reservation(point_id=self.point.pk, identity=self.identity,
                                     credentials=grant.credentials)

    def submit(self, operation, barrier=None):
        pids = Queue()

        def run():
            # Each thread owns its own Django/psycopg connection.
            db = connections["default"]
            try:
                with db.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.put(cursor.fetchone()[0])
                if barrier:
                    barrier.wait(timeout=10)
                try:
                    return operation()
                except r.ReservationError as error:
                    return type(error)
            finally:
                db.close()

        future = self.executor.submit(run)
        return future, pids.get(timeout=10)

    def race(self, first, second):
        barrier = Barrier(3)
        one, pid1 = self.submit(first, barrier)
        two, pid2 = self.submit(second, barrier)
        self.assertNotEqual(pid1, pid2)
        barrier.wait(timeout=10)
        return one.result(timeout=12), two.result(timeout=12)

    def wait_for_lock(self, pid, future=None):
        deadline = monotonic() + 4
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            main_pid = cursor.fetchone()[0]
        while monotonic() < deadline:
            if future is not None and future.done():
                # Surface worker exceptions rather than masking them as a lock timeout.
                result = future.result()
                if hasattr(result, "status_code"):
                    content_type = result.get("Content-Type", "")
                    code = result.json().get("code") if "application/json" in content_type else None
                    detail = f"HTTP {result.status_code}, content_type={content_type}, code={code}"
                else:
                    detail = result.__name__ if isinstance(result, type) else type(result).__name__
                # Never include response bodies or acquisition credentials.
                self.fail(f"Worker finished before the expected database row lock: {detail}")
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_blocking_pids(%s)", [pid])
                if main_pid in cursor.fetchone()[0]:
                    return
            Event().wait(0.01)  # Poll the server condition, never infer ordering from delay.
        self.fail("Worker did not reach the expected database row lock")

    def lock_point(self):
        return SignalingPoint.objects.select_for_update().get(pk=self.point.pk)

    def assert_current(self, grant):
        row = WaypointReservation.objects.get(signaling_point=self.point)
        self.point.refresh_from_db()
        self.assertEqual(row.generation, grant.credentials.generation)
        self.assertEqual(self.point.reservation_generation, row.generation)
        self.assertEqual(WaypointReservation.objects.filter(signaling_point=self.point).count(), 1)
        with r.validate_reservation(point_id=self.point.pk, identity=self.identity,
                                    credentials=grant.credentials):
            pass

    def test_two_simultaneous_first_acquisitions_have_one_winner(self):
        results = self.race(self.acquire, self.acquire)
        grants = [value for value in results if isinstance(value, r.ReservationGrant)]
        self.assertEqual(len(grants), 1)
        self.assertIn(r.ReservationOccupied, results)
        self.assertEqual(grants[0].credentials.generation, 1)
        self.assert_current(grants[0])

    def test_acquisition_concurrent_with_renewal(self):
        grant = self.acquire()
        results = self.race(self.acquire, lambda: self.renew(grant))
        self.assertIn(r.ReservationOccupied, results)
        renewed = next(value for value in results if isinstance(value, r.ReservationGrant))
        self.assertEqual(renewed.credentials, grant.credentials)
        self.assert_current(renewed)

    def test_acquisition_concurrent_with_release(self):
        old = self.acquire()
        results = self.race(self.acquire, lambda: self.release(old))
        self.assertIn(True, results)
        grants = [value for value in results if isinstance(value, r.ReservationGrant)]
        if grants:
            self.assertEqual(grants[0].credentials.generation, old.credentials.generation + 1)
            self.assert_current(grants[0])
            with self.assertRaises(r.ReservationGenerationStale):
                self.release(old)
        else:
            self.assertIn(r.ReservationOccupied, results)
            self.assertIsNotNone(WaypointReservation.objects.get().released_at)

    def test_two_acquisitions_disputing_expired_reservation_have_one_winner(self):
        old = self.acquire()
        now = r._database_now()
        WaypointReservation.objects.update(
            acquired_at=now-timedelta(seconds=3), renewed_at=now-timedelta(seconds=2),
            expires_at=now-timedelta(seconds=1),
        )
        results = self.race(self.acquire, self.acquire)
        grants = [value for value in results if isinstance(value, r.ReservationGrant)]
        self.assertEqual(len(grants), 1)
        self.assertIn(r.ReservationOccupied, results)
        self.assertEqual(grants[0].credentials.generation, old.credentials.generation + 1)
        self.assert_current(grants[0])

    def test_waiting_renewal_observes_expiration_after_lock_not_transaction_start(self):
        grant = self.acquire()
        with transaction.atomic():
            self.lock_point()
            pending, pid = self.submit(lambda: self.renew(grant))
            self.wait_for_lock(pid)
            # This instant is AFTER the worker's transaction began.
            WaypointReservation.objects.update(expires_at=r._database_now())
        self.assertIs(pending.result(timeout=12), r.ReservationExpired)

    def test_old_waiting_request_cannot_mutate_new_acquisition(self):
        old = self.acquire()

        def stale_mutation():
            with r.validate_reservation(point_id=self.point.pk, identity=self.identity,
                                        credentials=old.credentials) as point:
                point.status = "ABSENT"
                point.save(update_fields=["status"])
            return "unexpected mutation"

        with transaction.atomic():
            self.lock_point()
            pending, pid = self.submit(stale_mutation)
            self.wait_for_lock(pid)
            self.release(old)
            new = self.acquire()
        self.assertIs(pending.result(timeout=12), r.ReservationGenerationStale)
        self.point.refresh_from_db()
        self.assertEqual(self.point.status, "OK")
        self.assert_current(new)

    def test_validation_scope_holds_lock_through_mutation(self):
        grant = self.acquire()
        with r.validate_reservation(point_id=self.point.pk, identity=self.identity,
                                    credentials=grant.credentials) as point:
            pending, pid = self.submit(self.acquire)
            self.wait_for_lock(pid)
            point.status = "ABSENT"
            point.save(update_fields=["status"])
        self.assertIs(pending.result(timeout=12), r.ReservationOccupied)
        self.point.refresh_from_db()
        self.assertEqual(self.point.status, "ABSENT")
        self.assert_current(grant)

    def test_session_expiration_while_waiting_is_rechecked(self):
        grant = self.acquire()
        with transaction.atomic():
            self.lock_point()
            pending, pid = self.submit(lambda: self.renew(grant))
            self.wait_for_lock(pid)
            Session.objects.filter(session_key=self.identity.session_key).update(
                expire_date=r._database_now(),
            )
        self.assertIs(pending.result(timeout=12), r.ReservationAuthenticationRequired)
