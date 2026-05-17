"""Django app config for runtime orchestration."""

from django.apps import AppConfig


class RuntimeConfig(AppConfig):
    """Runtime app containing request gate and quota state."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "runtime"
