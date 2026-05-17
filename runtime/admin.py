"""Admin registration for runtime models."""

from __future__ import annotations

from django.contrib import admin

from runtime.models import OperationalLog, UsageQuotaWindow


@admin.register(UsageQuotaWindow)
class UsageQuotaWindowAdmin(admin.ModelAdmin):
    """Admin view for quota windows."""

    list_display = (
        "id",
        "user",
        "guest_identity",
        "window_started_at",
        "window_ends_at",
        "used_tokens",
        "token_limit",
        "is_exhausted",
        "updated_at",
    )
    list_filter = ("is_exhausted", "window_started_at", "window_ends_at")
    search_fields = ("id", "user__email", "guest_identity__id")
    date_hierarchy = "window_started_at"
    ordering = ("-window_started_at",)
    readonly_fields = ("id", "created_at", "updated_at")
    actions = ("reset_usage_state", "clear_pending_input_state")

    @admin.action(description="Reset selected windows usage counters (used_tokens=0, is_exhausted=false)")
    def reset_usage_state(self, request, queryset):
        queryset.update(used_tokens=0, is_exhausted=False)

    @admin.action(description="Clear selected pending_input buffer")
    def clear_pending_input_state(self, request, queryset):
        queryset.update(
            pending_input_text="",
            pending_input_append_count=0,
            pending_input_updated_at=None,
        )


@admin.register(OperationalLog)
class OperationalLogAdmin(admin.ModelAdmin):
    """Admin view for operational diagnostics."""

    list_display = ("created_at", "level", "event_key", "component", "turn", "user", "guest_identity")
    list_filter = ("level", "event_key", "component", "created_at")
    search_fields = ("event_key", "component", "message", "turn__id", "user__email", "guest_identity__id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = [field.name for field in OperationalLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
