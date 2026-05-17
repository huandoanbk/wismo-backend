import os

from .settings import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = [x for x in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if x]
