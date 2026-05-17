"""Django app config for MVP chat persistence."""

from django.apps import AppConfig


class ChatConfig(AppConfig):
    """Chat app containing Case, Chat, and ChatTurn."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "chat"
