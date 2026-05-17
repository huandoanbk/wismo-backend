"""Django app config for LLM operation routing."""

from django.apps import AppConfig


class LlmOpsConfig(AppConfig):
    """LLM operation gateway app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "llm_ops"
