"""Shared pytest configuration."""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wismo.settings_dev")
