from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ReservationMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_existing_point_and_children(self):
        executor = MigrationExecutor(connection)
        before = ("signaling", "0008_signalingpoint_report_permission")
        after = ("signaling", "0009_waypoint_reservation")
        try:
            executor.migrate([before])
            apps = executor.loader.project_state([before]).apps
            point = apps.get_model("signaling", "SignalingPoint").objects.create(
                latitude="-21.17", longitude="-47.81", status="OK",
            )
            intervention = apps.get_model("signaling", "SignalingIntervention").objects.create(
                signaling_point=point, type="R1", condition="OK", notes="preserved",
            )
            executor = MigrationExecutor(connection)
            executor.migrate([after])
            apps = executor.loader.project_state([after]).apps
            restored = apps.get_model("signaling", "SignalingPoint").objects.get(pk=point.pk)
            self.assertEqual(restored.reservation_generation, 0)
            self.assertEqual(restored.status, "OK")
            self.assertEqual(restored.interventions.get(pk=intervention.pk).notes, "preserved")
            self.assertFalse(apps.get_model("signaling", "WaypointReservation").objects.exists())
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
