"""Dedicated command settings: no HTTP credentials, sessions, storage or routes.

Run manage.py dispatch_report_publication --settings=config.report_dispatch_settings.
The command uses only REPORT_DISPATCH_DSN; the dummy backend forbids ORM access.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "dispatcher-does-not-sign-http-data"
USE_TZ = True
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "signaling"]
DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}
REPORT_DISPATCH_ENABLED = os.environ.get("REPORT_DISPATCH_ENABLED", "false").lower() == "true"
REPORT_DISPATCH_DSN = os.environ.get("REPORT_DISPATCH_DSN", "")
REPORT_EXECUTOR_RELEASE_ID = os.environ.get("REPORT_EXECUTOR_RELEASE_ID", "")
