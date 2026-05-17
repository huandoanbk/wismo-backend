"""LLM Gateway routing and usage persistence."""

from __future__ import annotations

import uuid

from django.db import models

from chat.models import enum_choices
from wismo.contracts.enums import LLMGatewayIntegrationKind, LLMGatewayMode, LLMUsageStatus


class LLMGatewayConfig(models.Model):
    """Canonical gateway config for one provider integration."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=120, unique=True)
    integration_kind = models.CharField(
        max_length=40,
        choices=enum_choices(LLMGatewayIntegrationKind),
    )
    endpoint_url = models.CharField(max_length=500)
    api_key_ref = models.CharField(max_length=120)
    model_name = models.CharField(max_length=120)
    mode = models.CharField(
        max_length=20,
        choices=enum_choices(LLMGatewayMode),
    )
    params = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "llm_gateway_configs"
        ordering = ("display_name",)
        indexes = [
            models.Index(fields=["integration_kind", "is_active"], name="idx_llm_gateway_kind_active"),
        ]

    def __str__(self) -> str:
        """Return the operator-facing gateway label."""

        return self.display_name


class LLMOperation(models.Model):
    """Canonical LLM operation registry entry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True)
    gateway = models.ForeignKey(
        "llm_ops.LLMGatewayConfig",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="operations",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "llm_operations"
        ordering = ("code",)
        indexes = [
            models.Index(fields=["gateway", "is_active"], name="idx_llm_op_gw_active"),
        ]

    def __str__(self) -> str:
        """Return the canonical operation code."""

        return self.code


class LLMUsageEvent(models.Model):
    """Usage event for one LLM operation in a turn."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    turn = models.ForeignKey(
        "chat.ChatTurn",
        on_delete=models.CASCADE,
        related_name="llm_usage_events",
    )
    operation_key = models.CharField(max_length=120)
    supplier_name = models.CharField(max_length=80)
    model_name = models.CharField(max_length=120)
    input_tokens = models.PositiveIntegerField(default=0)
    cached_input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    total_billable_tokens = models.PositiveIntegerField(default=0)
    total_observed_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=enum_choices(LLMUsageStatus),
        default=LLMUsageStatus.SUCCESS.value,
    )
    error_code = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "llm_usage_events"
        indexes = [
            models.Index(fields=["created_at"], name="idx_usage_created_at"),
            models.Index(fields=["operation_key", "created_at"], name="idx_usage_operation_time"),
            models.Index(fields=["supplier_name", "model_name"], name="idx_usage_supplier_model"),
        ]

    def save(self, *args, **kwargs) -> None:
        """Keep usage totals consistent before persistence."""

        self.total_billable_tokens = (
            self.input_tokens
            + self.cached_input_tokens
            + self.output_tokens
            + self.cache_write_tokens
        )
        self.total_observed_tokens = self.total_billable_tokens
        super().save(*args, **kwargs)
