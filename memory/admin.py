"""Admin registration for memory models."""

from __future__ import annotations

import json

from django.contrib import admin
from django.utils.html import format_html

from memory.models import MemoryItem, UserPreferenceState, UserProfileState, UserStateSnapshot


@admin.register(MemoryItem)
class MemoryItemAdmin(admin.ModelAdmin):
    """Admin view for long-term memory items."""

    list_display = (
        "id",
        "user",
        "guest_identity",
        "case",
        "segment_status",
        "user_concern_preview",
        "assistant_approach_preview",
        "user_response_preview",
        "state_shift_preview",
        "updated_at",
        "created_at",
    )
    list_filter = ("segment_status",)
    search_fields = (
        "user_concern_summary",
        "assistant_approach_summary",
        "user_response_summary",
        "state_shift",
        "case__id",
        "user__email",
        "guest_identity__id",
    )
    readonly_fields = (
        "user_concern_pretty",
        "assistant_approach_pretty",
        "user_response_pretty",
        "state_shift_pretty",
        "open_loops_pretty",
        "confidence",
        "start_turn",
        "end_turn",
        "created_at",
        "updated_at",
    )

    @admin.display(description="user_concern_summary")
    def user_concern_preview(self, obj: MemoryItem) -> str:
        text = (obj.user_concern_summary or "").strip()
        return f"{text[:160]}..." if len(text) > 160 else text

    @admin.display(description="assistant_approach_summary")
    def assistant_approach_preview(self, obj: MemoryItem) -> str:
        text = (obj.assistant_approach_summary or "").strip()
        return f"{text[:160]}..." if len(text) > 160 else text

    @admin.display(description="user_response_summary")
    def user_response_preview(self, obj: MemoryItem) -> str:
        text = (obj.user_response_summary or "").strip()
        return f"{text[:160]}..." if len(text) > 160 else text

    @admin.display(description="state_shift")
    def state_shift_preview(self, obj: MemoryItem) -> str:
        text = (obj.state_shift or "").strip()
        return f"{text[:160]}..." if len(text) > 160 else text

    @admin.display(description="user_concern_summary_full")
    def user_concern_pretty(self, obj: MemoryItem) -> str:
        text = (obj.user_concern_summary or "").strip()
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", text)

    @admin.display(description="assistant_approach_summary_full")
    def assistant_approach_pretty(self, obj: MemoryItem) -> str:
        text = (obj.assistant_approach_summary or "").strip()
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", text)

    @admin.display(description="user_response_summary_full")
    def user_response_pretty(self, obj: MemoryItem) -> str:
        text = (obj.user_response_summary or "").strip()
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", text)

    @admin.display(description="state_shift_full")
    def state_shift_pretty(self, obj: MemoryItem) -> str:
        text = (obj.state_shift or "").strip()
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", text)

    @admin.display(description="open_loops")
    def open_loops_pretty(self, obj: MemoryItem) -> str:
        pretty = json.dumps(obj.open_loops if isinstance(obj.open_loops, list) else [], ensure_ascii=False, indent=2)
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", pretty)


@admin.register(UserProfileState)
class UserProfileStateAdmin(admin.ModelAdmin):
    """Admin view for identity-scoped profile state."""

    list_display = ("id", "user", "guest_identity", "profile_facts_preview", "version", "updated_at")
    search_fields = ("id", "user__email", "guest_identity__id")
    readonly_fields = ("profile_facts_pretty", "created_at", "updated_at")

    @admin.display(description="profile_facts")
    def profile_facts_preview(self, obj: UserProfileState) -> str:
        profile_data = obj.profile_data if isinstance(obj.profile_data, dict) else {}
        facts = profile_data.get("facts")
        if not isinstance(facts, list):
            return "[]"
        values = [item.strip() for item in facts if isinstance(item, str) and item.strip()]
        if not values:
            return "[]"
        text = " | ".join(values)
        return f"{text[:160]}..." if len(text) > 160 else text

    @admin.display(description="profile_facts_full")
    def profile_facts_pretty(self, obj: UserProfileState) -> str:
        profile_data = obj.profile_data if isinstance(obj.profile_data, dict) else {}
        pretty = json.dumps(profile_data.get("facts", []), ensure_ascii=False, indent=2)
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", pretty)


@admin.register(UserPreferenceState)
class UserPreferenceStateAdmin(admin.ModelAdmin):
    """Admin view for identity-scoped preference state."""

    list_display = ("id", "user", "guest_identity", "style_signals_preview", "updated_at")
    search_fields = ("id", "user__email", "guest_identity__id")
    readonly_fields = ("style_signals_pretty", "created_at", "updated_at")

    @admin.display(description="style_signals")
    def style_signals_preview(self, obj: UserPreferenceState) -> str:
        data = obj.preference_data if isinstance(obj.preference_data, dict) else {}
        signals = [key for key, value in data.items() if value is True]
        if not signals:
            return "[]"
        text = ", ".join(sorted(signals))
        return f"{text[:160]}..." if len(text) > 160 else text

    @admin.display(description="style_signals_full")
    def style_signals_pretty(self, obj: UserPreferenceState) -> str:
        data = obj.preference_data if isinstance(obj.preference_data, dict) else {}
        signals = [key for key, value in data.items() if value is True]
        pretty = json.dumps(sorted(signals), ensure_ascii=False, indent=2)
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", pretty)


@admin.register(UserStateSnapshot)
class UserStateSnapshotAdmin(admin.ModelAdmin):
    """Admin view for identity-scoped state snapshot."""

    list_display = (
        "id",
        "user",
        "guest_identity",
        "primary_state",
        "secondary_state",
        "user_state_signals_preview",
        "updated_at",
    )
    list_filter = ("primary_state",)
    search_fields = ("id", "user__email", "guest_identity__id")
    readonly_fields = ("user_state_signals_pretty", "created_at", "updated_at")

    @admin.display(description="user_state_signals")
    def user_state_signals_preview(self, obj: UserStateSnapshot) -> str:
        signals = obj.raw_signals if isinstance(obj.raw_signals, list) else []
        values = [item.strip() for item in signals if isinstance(item, str) and item.strip()]
        if not values:
            return "[]"
        text = ", ".join(values)
        return f"{text[:160]}..." if len(text) > 160 else text

    @admin.display(description="user_state_signals_full")
    def user_state_signals_pretty(self, obj: UserStateSnapshot) -> str:
        signals = obj.raw_signals if isinstance(obj.raw_signals, list) else []
        pretty = json.dumps(signals, ensure_ascii=False, indent=2)
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", pretty)
