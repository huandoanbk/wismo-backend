"""Admin-controlled runtime configuration."""

from __future__ import annotations

import uuid

from django.db import models


class RuntimeConfig(models.Model):
    """Generic config record for runtime limits and feature flags."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=120, unique=True)
    value = models.JSONField(default=dict)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "runtime_configs"
        ordering = ("key",)

    def __str__(self) -> str:
        """Return the config key for admin display."""

        return self.key
