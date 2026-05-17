"""Django app config for account and identity models."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Accounts app containing registered and guest identity state."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
