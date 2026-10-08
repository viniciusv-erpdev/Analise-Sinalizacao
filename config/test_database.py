from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.database import database_config


class DatabaseConfigurationTests(SimpleTestCase):
    base_dir = Path("development")
    postgres = {
        "DJANGO_DB_BACKEND": "postgresql", "POSTGRES_DB": "analysis",
        "POSTGRES_USER": "application", "POSTGRES_PASSWORD": " test password ",
        "POSTGRES_HOST": "127.0.0.1",
    }

    def test_development_defaults_to_sqlite(self):
        config = database_config(self.base_dir, debug=True, environ={})
        self.assertEqual(config["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(config["NAME"], self.base_dir / "db.sqlite3")

    def test_production_requires_explicit_backend(self):
        for value in ("", " "):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                database_config(self.base_dir, debug=False, environ={"DJANGO_DB_BACKEND": value})

    def test_production_can_explicitly_keep_sqlite(self):
        config = database_config(self.base_dir, debug=False, environ={
            "DJANGO_DB_BACKEND": "sqlite", "DJANGO_SQLITE_PATH": "backup.sqlite3",
        })
        self.assertEqual(config["NAME"], "backup.sqlite3")

    def test_invalid_backend_fails_even_in_development(self):
        with self.assertRaises(ImproperlyConfigured):
            database_config(self.base_dir, debug=True, environ={"DJANGO_DB_BACKEND": "postgres"})

    def test_postgresql_preserves_password_and_never_connects_during_configuration(self):
        with patch("django.db.backends.base.base.BaseDatabaseWrapper.connect", side_effect=AssertionError):
            config = database_config(self.base_dir, debug=False, environ=self.postgres)
        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["PASSWORD"], " test password ")
        self.assertEqual(config["PORT"], "5432")
        self.assertEqual(config["OPTIONS"]["connect_timeout"], 10)

    def test_missing_postgresql_fields_fail_without_exposing_password(self):
        for name in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST"):
            for value in ("", " "):
                env = {**self.postgres, name: value}
                with self.subTest(name=name, value=value), self.assertRaises(ImproperlyConfigured) as error:
                    database_config(self.base_dir, debug=True, environ=env)
                self.assertIn(name, str(error.exception))
                self.assertNotIn("test password", str(error.exception))

    def test_port_validation(self):
        for port in ("", "abc", "0", "65536"):
            with self.subTest(port=port), self.assertRaises(ImproperlyConfigured):
                database_config(self.base_dir, debug=True, environ={**self.postgres, "POSTGRES_PORT": port})

    def test_separate_test_database(self):
        config = database_config(self.base_dir, debug=True, environ={**self.postgres, "DJANGO_TEST_DB_NAME": "test_analysis"})
        self.assertEqual(config["TEST"]["NAME"], "test_analysis")
        with self.assertRaises(ImproperlyConfigured):
            database_config(self.base_dir, debug=True, environ={**self.postgres, "DJANGO_TEST_DB_NAME": "analysis"})
