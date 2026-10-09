"""Database selection without connection-time fallback or secret defaults."""
import os

from django.core.exceptions import ImproperlyConfigured


def database_config(base_dir, *, debug, environ=None):
    env = os.environ if environ is None else environ
    backend = env.get("DJANGO_DB_BACKEND", "").strip().lower()
    if not backend:
        if not debug:
            raise ImproperlyConfigured("DJANGO_DB_BACKEND is required when DJANGO_DEBUG=False.")
        backend = "sqlite"
    if backend == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": env.get("DJANGO_SQLITE_PATH", "").strip() or base_dir / "db.sqlite3"}
    if backend != "postgresql":
        raise ImproperlyConfigured("DJANGO_DB_BACKEND must be sqlite or postgresql.")
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST")
    for name in required:
        if not env.get(name, "").strip():
            raise ImproperlyConfigured(f"{name} is required for PostgreSQL.")
    port = env.get("POSTGRES_PORT", "5432").strip()
    try:
        valid_port = 1 <= int(port) <= 65535
    except ValueError:
        valid_port = False
    if not valid_port:
        raise ImproperlyConfigured("POSTGRES_PORT must be an integer between 1 and 65535.")
    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env["POSTGRES_DB"].strip(),
        "USER": env["POSTGRES_USER"].strip(),
        "PASSWORD": env["POSTGRES_PASSWORD"],
        "HOST": env["POSTGRES_HOST"].strip(),
        "PORT": port,
        "OPTIONS": {"connect_timeout": 10},
    }
    test_name = env.get("DJANGO_TEST_DB_NAME", "").strip()
    if test_name:
        if test_name == config["NAME"]:
            raise ImproperlyConfigured("DJANGO_TEST_DB_NAME must differ from POSTGRES_DB.")
        config["TEST"] = {"NAME": test_name}
    return config
