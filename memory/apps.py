"""Django app config for memory foundation."""

from django.apps import AppConfig


class MemoryConfig(AppConfig):
    """Memory app for case-scoped long-term memory items."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "memory"
