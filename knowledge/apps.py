"""Django app config for runtime knowledge retrieval."""

from django.apps import AppConfig


class KnowledgeConfig(AppConfig):
    """Knowledge app for vector retrieval tables populated externally."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "knowledge"
