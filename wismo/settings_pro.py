import os
from .settings import *

DEBUG = False
ALLOWED_HOSTS = [x for x in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if x]