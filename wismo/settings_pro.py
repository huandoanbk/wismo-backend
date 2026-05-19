import os
from pathlib import Path

from .settings import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = [x for x in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if x]

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_ROOT = BASE_DIR / "staticfiles"
