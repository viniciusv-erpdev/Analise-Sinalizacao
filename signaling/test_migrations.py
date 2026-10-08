from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MultipleInterventionsMigrationTests(TransactionTestCase):
    migrate_from = ("signaling", "0002_signalingintervention_unique_intervention_type_per_signaling_point")
    migrate_to = (
        "signaling",
        "0003_remove_signalingintervention_unique_intervention_type_per_signaling_point_and_more",
    )

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        SignalingPoint = old_apps.get_model("signaling", "SignalingPoint")
        SignalingIntervention = old_apps.get_model(
            "signaling",
            "SignalingIntervention",
        )
        point = SignalingPoint.objects.create(
            latitude="-21.170000",
            longitude="-47.810000",
            status="INCOMPLETE",
        )
        self.intervention_id = SignalingIntervention.objects.create(
            signaling_point=point,
            type="TRAFFIC_LIGHT",
            condition="OK",
        ).id

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_traffic_light_survives_migration(self):
        SignalingIntervention = self.apps.get_model(
            "signaling",
            "SignalingIntervention",
        )

        intervention = SignalingIntervention.objects.get(pk=self.intervention_id)

        self.assertEqual(intervention.type, "TRAFFIC_LIGHT")
        self.assertEqual(intervention.condition, "OK")


class InterventionNotesMigrationTests(TransactionTestCase):
    migrate_from = (
        "signaling",
        "0003_remove_signalingintervention_unique_intervention_type_per_signaling_point_and_more",
    )
    migrate_to = ("signaling", "0004_signalingintervention_notes")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        SignalingPoint = old_apps.get_model("signaling", "SignalingPoint")
        SignalingIntervention = old_apps.get_model(
            "signaling",
            "SignalingIntervention",
        )
        point = SignalingPoint.objects.create(
            latitude="-21.170000",
            longitude="-47.810000",
            status="INCOMPLETE",
        )
        self.intervention_id = SignalingIntervention.objects.create(
            signaling_point=point,
            type="TRAFFIC_LIGHT",
            condition="OK",
        ).id

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_intervention_receives_empty_notes(self):
        SignalingIntervention = self.apps.get_model(
            "signaling",
            "SignalingIntervention",
        )

        intervention = SignalingIntervention.objects.get(pk=self.intervention_id)

        self.assertEqual(intervention.notes, "")
