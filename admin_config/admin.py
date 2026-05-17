"""Admin registration for runtime config."""

from __future__ import annotations

import json

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest

from admin_config.defaults import (
    ensure_runtime_config_defaults,
    runtime_config_default_specs,
    validate_runtime_config_value,
)
from admin_config.models import RuntimeConfig


class RuntimeConfigModelForm(forms.ModelForm):
    """Validate runtime config value shape against canonical default specs."""

    class Meta:
        model = RuntimeConfig
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        key = str(cleaned.get("key") or "")
        value = cleaned.get("value")
        if key and value is not None:
            try:
                cleaned["value"] = validate_runtime_config_value(key=key, value=value)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        return cleaned


@admin.register(RuntimeConfig)
class RuntimeConfigAdmin(admin.ModelAdmin):
    """Admin view for runtime config key/value records."""

    change_list_template = "admin/admin_config/runtimeconfig/change_list.html"
    form = RuntimeConfigModelForm
    list_display = ("key", "is_active", "updated_at")
    list_filter = ("is_active", "updated_at")
    search_fields = ("key",)
    ordering = ("key",)

    def changelist_view(self, request: HttpRequest, extra_context=None):
        """Render runtime config list with default table and sync action."""

        if request.GET.get("sync_defaults") == "1":
            result = ensure_runtime_config_defaults()
            self.message_user(
                request,
                (
                    "Runtime config defaults synced. "
                    f"created={result.created_count}, "
                    f"description_updated={result.updated_description_count}, "
                    f"activated={result.activated_count}"
                ),
                level=messages.SUCCESS,
            )

        rows = []
        records = {
            record.key: record
            for record in RuntimeConfig.objects.order_by("key", "-updated_at", "-created_at")
        }
        for spec in runtime_config_default_specs():
            record = records.get(spec.key)
            current_value = record.value if record is not None and isinstance(record.value, dict) else None
            rows.append(
                {
                    "key": spec.key,
                    "description": spec.description,
                    "default_value_json": json.dumps(spec.default_value, ensure_ascii=False, indent=2),
                    "current_value_json": json.dumps(current_value, ensure_ascii=False, indent=2) if current_value is not None else "",
                    "exists": record is not None,
                    "is_active": bool(record.is_active) if record is not None else False,
                    "is_default_match": current_value == spec.default_value if current_value is not None else False,
                }
            )

        extra = extra_context or {}
        extra["runtime_config_defaults"] = rows
        return super().changelist_view(request, extra_context=extra)
