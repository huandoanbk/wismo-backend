"""Model shape tests that do not require database access."""

from django.apps import apps


def field_names(model) -> set[str]:
    """Return concrete field names for a Django model."""

    return {field.name for field in model._meta.fields}


def test_chat_case_turn_models_replace_legacy_message_model() -> None:
    """Chat foundation exposes Case, Chat, ChatTurn and not old Message."""

    case_model = apps.get_model("chat", "Case")
    chat_model = apps.get_model("chat", "Chat")
    turn_model = apps.get_model("chat", "ChatTurn")

    assert {"topic", "context_summary", "last_activity_at"} <= field_names(case_model)
    assert {"case", "chat_display_name", "opening_input_text"} <= field_names(chat_model)
    assert {
        "user_message_text",
        "assistant_response_text",
        "response_method",
        "status",
        "runtime_metadata",
        "usage_accounting_status",
        "step12_finalization_status",
    } <= field_names(turn_model)
    assert "Message" not in {model.__name__ for model in apps.get_app_config("chat").get_models()}


def test_foundation_apps_are_installed_without_old_apps(settings) -> None:
    """Installed apps match the reset MVP module boundary."""

    installed = set(settings.INSTALLED_APPS)

    assert {
        "accounts",
        "consents",
        "chat",
        "runtime",
        "llm_ops",
        "memory",
        "knowledge",
        "admin_config",
    } <= installed
    assert not {"counseling", "personalization", "safety", "telemetry", "llm"} & installed
