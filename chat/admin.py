"""Admin registration for chat foundation models."""

from __future__ import annotations

import json

from django.contrib import admin
from django.utils.html import format_html

from chat.models import Case, Chat, ChatTurn
from llm_ops.models import LLMUsageEvent
from runtime.models import OperationalLog


class LLMUsageEventInline(admin.TabularInline):
    """Read-only inline usage events for one turn."""

    model = LLMUsageEvent
    extra = 0
    can_delete = False
    fields = (
        "created_at",
        "operation_key",
        "supplier_name",
        "model_name",
        "status",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "cache_write_tokens",
        "total_billable_tokens",
        "latency_ms",
        "error_code",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class OperationalLogInline(admin.TabularInline):
    """Read-only inline operational logs for one turn."""

    model = OperationalLog
    extra = 0
    can_delete = False
    fields = ("created_at", "level", "event_key", "component", "message")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    """Admin view for backend continuity cases."""

    list_display = (
        "id",
        "user",
        "guest_identity",
        "topic",
        "context_summary_preview",
        "status",
        "phase",
        "last_activity_at",
    )
    list_filter = ("status", "phase", "created_at", "last_activity_at")
    search_fields = ("topic", "context_summary")
    readonly_fields = ("context_summary_pretty",)
    date_hierarchy = "last_activity_at"
    ordering = ("-last_activity_at",)

    @admin.display(description="context_summary")
    def context_summary_preview(self, obj: Case) -> str:
        text = (obj.context_summary or "").strip()
        return f"{text[:160]}..." if len(text) > 160 else text

    @admin.display(description="context_summary_full")
    def context_summary_pretty(self, obj: Case) -> str:
        text = (obj.context_summary or "").strip()
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", text)


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    """Admin view for frontend chat threads."""

    list_display = ("id", "chat_display_name", "user", "guest_identity", "case", "last_activity_at")
    list_filter = ("is_archived", "is_pending_case_confirmation", "last_activity_at")
    search_fields = ("id", "chat_display_name", "opening_input_text", "user__email", "guest_identity__id")
    date_hierarchy = "last_activity_at"
    ordering = ("-last_activity_at",)


@admin.register(ChatTurn)
class ChatTurnAdmin(admin.ModelAdmin):
    """Admin view for persisted chat turns."""

    list_display = (
        "id",
        "chat",
        "triage_decision",
        "response_method",
        "status",
        "usage_accounting_status",
        "step12_finalization_status",
        "quota_exhausted_after_turn",
        "created_at",
    )
    list_filter = (
        "triage_decision",
        "response_method",
        "status",
        "usage_accounting_status",
        "step12_finalization_status",
        "created_at",
    )
    search_fields = (
        "id",
        "chat__id",
        "case__id",
        "user__email",
        "guest_identity__id",
        "user_message_text",
        "assistant_response_text",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "chat",
        "case",
        "user",
        "guest_identity",
        "user_message_text",
        "assistant_response_text",
        "response_method",
        "triage_decision",
        "status",
        "runtime_metadata",
        "step_trace_details",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "cache_write_tokens",
        "total_billable_tokens",
        "total_observed_tokens",
        "quota_window_before",
        "quota_window_after",
        "quota_exhausted_after_turn",
        "usage_accounting_status",
        "step12_finalization_status",
        "created_at",
        "finalized_at",
    )
    inlines = (LLMUsageEventInline, OperationalLogInline)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="step traces")
    def step_trace_details(self, obj: ChatTurn) -> str:
        """Render runtime step traces from runtime_metadata in a readable JSON block."""

        metadata = obj.runtime_metadata if isinstance(obj.runtime_metadata, dict) else {}
        traces = metadata.get("step_traces", [])
        if not isinstance(traces, list) or not traces:
            return "[]"
        pretty = json.dumps(traces, ensure_ascii=False, indent=2)
        return format_html("<pre style='white-space: pre-wrap; max-width: 1200px;'>{}</pre>", pretty)
