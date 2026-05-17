"""Django app config for consent records."""

from django.apps import AppConfig


class ConsentsConfig(AppConfig):
    """Consent app containing pre-chat consent state."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "consents"
