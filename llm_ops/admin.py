"""Admin registration for LLM operation models."""

from __future__ import annotations

from datetime import date

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date

from llm_ops.models import LLMGatewayConfig, LLMOperation, LLMUsageEvent
from llm_ops.services import LLMUsageQueryService
from wismo.contracts.enums import OperationKey


class LLMGatewayConfigModelForm(forms.ModelForm):
    """Validate gateway config payload before save."""

    class Meta:
        model = LLMGatewayConfig
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        params = cleaned.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValidationError("params must be a JSON object.")
        cleaned["params"] = params

        if cleaned.get("is_active"):
            required = ("display_name", "endpoint_url", "api_key_ref", "model_name")
            for field_name in required:
                if not str(cleaned.get(field_name) or "").strip():
                    raise ValidationError(f"{field_name} is required for active gateway config.")
            if params.get("adapter") == "local_stub" and not params.get("allow_stub"):
                raise ValidationError("local_stub adapter requires params.allow_stub=true.")
        return cleaned


class OperationRoutingHealthFilter(admin.SimpleListFilter):
    """Filter operations by effective routing health state."""

    title = "routing health"
    parameter_name = "routing_health"

    def lookups(self, request, model_admin):
        return (
            ("ok", "ok"),
            ("missing_gateway", "missing gateway"),
            ("inactive_gateway", "inactive gateway"),
            ("inactive_operation", "inactive operation"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "ok":
            return queryset.filter(is_active=True, gateway__isnull=False, gateway__is_active=True)
        if value == "missing_gateway":
            return queryset.filter(gateway__isnull=True)
        if value == "inactive_gateway":
            return queryset.filter(gateway__isnull=False, gateway__is_active=False)
        if value == "inactive_operation":
            return queryset.filter(is_active=False)
        return queryset


class LLMOperationModelForm(forms.ModelForm):
    """Validate operation-level gateway routing, including optional fallback routing."""

    class Meta:
        model = LLMOperation
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        code = str(cleaned.get("code") or "").strip()
        gateway = cleaned.get("gateway")
        fallback_gateway = cleaned.get("fallback_gateway")

        if fallback_gateway is not None and code != OperationKey.RESPONSE_GENERATION.value:
            raise ValidationError("fallback_gateway is only supported for response_generation.")
        if gateway is not None and fallback_gateway is not None and gateway.pk == fallback_gateway.pk:
            raise ValidationError("fallback_gateway must be different from gateway.")
        return cleaned


@admin.register(LLMGatewayConfig)
class LLMGatewayConfigAdmin(admin.ModelAdmin):
    """Admin view for canonical gateway configuration."""

    form = LLMGatewayConfigModelForm
    list_display = ("display_name", "integration_kind", "model_name", "mode", "is_active", "created_at")
    list_filter = ("integration_kind", "mode", "is_active")
    search_fields = ("display_name", "endpoint_url", "model_name")


@admin.register(LLMOperation)
class LLMOperationAdmin(admin.ModelAdmin):
    """Admin view for LLM operations and gateway bindings."""

    form = LLMOperationModelForm
    list_display = ("code", "description", "gateway", "fallback_gateway", "routing_health", "is_active", "created_at")
    list_filter = ("is_active", "gateway", OperationRoutingHealthFilter)
    search_fields = ("code", "description", "gateway__display_name")
    autocomplete_fields = ("gateway", "fallback_gateway")
    ordering = ("code",)

    @admin.display(description="routing health")
    def routing_health(self, obj: LLMOperation) -> str:
        """Return one routing-health bucket for operator visibility."""

        if not obj.is_active:
            return "inactive_operation"
        if obj.gateway is None:
            return "missing_gateway"
        if not obj.gateway.is_active:
            return "inactive_gateway"
        return "ok"


@admin.register(LLMUsageEvent)
class LLMUsageEventAdmin(admin.ModelAdmin):
    """Admin view for LLM usage events."""

    change_list_template = "admin/llm_ops/llmusageevent/change_list.html"
    list_display = (
        "created_at",
        "turn",
        "operation_key",
        "supplier_name",
        "model_name",
        "status",
        "total_billable_tokens",
        "latency_ms",
    )
    list_filter = ("operation_key", "status", "supplier_name", "model_name", "created_at")
    list_select_related = ("turn",)
    search_fields = ("turn__id", "supplier_name", "model_name", "operation_key")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = [field.name for field in LLMUsageEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        """Apply report filters before rendering changelist rows."""

        queryset = super().get_queryset(request)
        start_date = self._parse_report_date(request.GET.get("report_start", ""))
        end_date = self._parse_report_date(request.GET.get("report_end", ""))
        gateway_name = request.GET.get("report_gateway", "").strip()
        if start_date is not None:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date is not None:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if gateway_name:
            queryset = queryset.filter(supplier_name=gateway_name)
        return queryset

    def changelist_view(self, request, extra_context=None):
        """Render the default changelist plus a per-gateway token usage report."""

        response = super().changelist_view(request, extra_context=extra_context)
        if not hasattr(response, "context_data"):
            return response

        changelist = response.context_data.get("cl")
        queryset = changelist.queryset if changelist is not None else self.get_queryset(request)
        report_service = LLMUsageQueryService()
        response.context_data["usage_report"] = {
            "totals": report_service.summarize_totals_from_queryset(queryset),
            "gateways": report_service.summarize_gateways_from_queryset(queryset),
            "operations": report_service.summarize_operations_from_queryset(queryset),
            "gateway_choices": report_service.gateway_name_choices_from_queryset(
                LLMUsageEvent.objects.all(),
            ),
            "filters": {
                "report_start": request.GET.get("report_start", ""),
                "report_end": request.GET.get("report_end", ""),
                "report_gateway": request.GET.get("report_gateway", ""),
            },
        }
        return response

    @staticmethod
    def _parse_report_date(raw_value: str) -> date | None:
        """Parse YYYY-MM-DD date values from admin report filters."""

        if not raw_value:
            return None
        return parse_date(raw_value)
