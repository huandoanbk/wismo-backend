"""Django app config for runtime admin configuration."""

from django.apps import AppConfig


class AdminConfigConfig(AppConfig):
    """Runtime configuration app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "admin_config"
