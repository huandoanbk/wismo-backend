"""LLM usage query helpers for admin and operational inspection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate

from llm_ops.models import LLMUsageEvent


@dataclass(frozen=True)
class LLMUsageDaySummary:
    """Aggregated usage totals for a single day."""

    day: date
    event_count: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    total_billable_tokens: int
    total_observed_tokens: int


@dataclass(frozen=True)
class LLMUsageTotals:
    """Total usage numbers for the current report queryset."""

    event_count: int
    success_count: int
    failed_count: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    total_billable_tokens: int
    total_observed_tokens: int
    avg_latency_ms: int


@dataclass(frozen=True)
class LLMGatewayUsageSummary:
    """Per-gateway usage aggregate row for admin reporting."""

    gateway_name: str
    event_count: int
    success_count: int
    failed_count: int
    total_billable_tokens: int
    total_observed_tokens: int
    avg_latency_ms: int


@dataclass(frozen=True)
class LLMOperationUsageSummary:
    """Per-operation usage aggregate row for admin reporting."""

    operation_key: str
    event_count: int
    success_count: int
    failed_count: int
    total_billable_tokens: int
    total_observed_tokens: int
    avg_latency_ms: int


class LLMUsageQueryService:
    """Query usage events with deterministic day-based aggregates."""

    def summarize_totals_from_queryset(self, queryset) -> LLMUsageTotals:
        """Return global totals for the currently filtered admin queryset."""

        aggregates = queryset.aggregate(
            event_count=Count("id"),
            success_count=Count("id", filter=Q(status="success")),
            failed_count=Count("id", filter=Q(status="failed")),
            input_tokens=Sum("input_tokens"),
            cached_input_tokens=Sum("cached_input_tokens"),
            output_tokens=Sum("output_tokens"),
            cache_write_tokens=Sum("cache_write_tokens"),
            total_billable_tokens=Sum("total_billable_tokens"),
            total_observed_tokens=Sum("total_observed_tokens"),
            avg_latency_ms=Avg("latency_ms"),
        )
        return LLMUsageTotals(
            event_count=aggregates["event_count"] or 0,
            success_count=aggregates["success_count"] or 0,
            failed_count=aggregates["failed_count"] or 0,
            input_tokens=aggregates["input_tokens"] or 0,
            cached_input_tokens=aggregates["cached_input_tokens"] or 0,
            output_tokens=aggregates["output_tokens"] or 0,
            cache_write_tokens=aggregates["cache_write_tokens"] or 0,
            total_billable_tokens=aggregates["total_billable_tokens"] or 0,
            total_observed_tokens=aggregates["total_observed_tokens"] or 0,
            avg_latency_ms=int(round(float(aggregates["avg_latency_ms"] or 0.0))),
        )

    def summarize_gateways_from_queryset(self, queryset) -> list[LLMGatewayUsageSummary]:
        """Return per-gateway usage aggregates for the currently filtered queryset."""

        rows = (
            queryset.values("supplier_name")
            .annotate(
                event_count=Count("id"),
                success_count=Count("id", filter=Q(status="success")),
                failed_count=Count("id", filter=Q(status="failed")),
                total_billable_tokens=Sum("total_billable_tokens"),
                total_observed_tokens=Sum("total_observed_tokens"),
                avg_latency_ms=Avg("latency_ms"),
            )
            .order_by("-total_billable_tokens", "supplier_name")
        )
        return [
            LLMGatewayUsageSummary(
                gateway_name=str(row["supplier_name"] or "unknown"),
                event_count=row["event_count"] or 0,
                success_count=row["success_count"] or 0,
                failed_count=row["failed_count"] or 0,
                total_billable_tokens=row["total_billable_tokens"] or 0,
                total_observed_tokens=row["total_observed_tokens"] or 0,
                avg_latency_ms=int(round(float(row["avg_latency_ms"] or 0.0))),
            )
            for row in rows
        ]

    def summarize_operations_from_queryset(self, queryset) -> list[LLMOperationUsageSummary]:
        """Return per-operation usage aggregates for the currently filtered queryset."""

        rows = (
            queryset.values("operation_key")
            .annotate(
                event_count=Count("id"),
                success_count=Count("id", filter=Q(status="success")),
                failed_count=Count("id", filter=Q(status="failed")),
                total_billable_tokens=Sum("total_billable_tokens"),
                total_observed_tokens=Sum("total_observed_tokens"),
                avg_latency_ms=Avg("latency_ms"),
            )
            .order_by("-total_billable_tokens", "operation_key")
        )
        return [
            LLMOperationUsageSummary(
                operation_key=str(row["operation_key"] or "unknown"),
                event_count=row["event_count"] or 0,
                success_count=row["success_count"] or 0,
                failed_count=row["failed_count"] or 0,
                total_billable_tokens=row["total_billable_tokens"] or 0,
                total_observed_tokens=row["total_observed_tokens"] or 0,
                avg_latency_ms=int(round(float(row["avg_latency_ms"] or 0.0))),
            )
            for row in rows
        ]

    def gateway_name_choices_from_queryset(self, queryset) -> list[str]:
        """Return sorted gateway names present in the queryset."""

        return [
            str(name)
            for name in queryset.exclude(supplier_name="").values_list("supplier_name", flat=True).distinct().order_by("supplier_name")
        ]

    def daily_summary(
        self,
        *,
        day: date,
        supplier_name: str | None = None,
        model_name: str | None = None,
        operation_key: str | None = None,
    ) -> LLMUsageDaySummary:
        """Return usage totals for one day with optional supplier/model filters."""

        queryset = self._filtered_queryset(
            day=day,
            supplier_name=supplier_name,
            model_name=model_name,
            operation_key=operation_key,
        )
        aggregates = queryset.aggregate(
            event_count=Count("id"),
            input_tokens=Sum("input_tokens"),
            cached_input_tokens=Sum("cached_input_tokens"),
            output_tokens=Sum("output_tokens"),
            cache_write_tokens=Sum("cache_write_tokens"),
            total_billable_tokens=Sum("total_billable_tokens"),
            total_observed_tokens=Sum("total_observed_tokens"),
        )
        return LLMUsageDaySummary(
            day=day,
            event_count=aggregates["event_count"] or 0,
            input_tokens=aggregates["input_tokens"] or 0,
            cached_input_tokens=aggregates["cached_input_tokens"] or 0,
            output_tokens=aggregates["output_tokens"] or 0,
            cache_write_tokens=aggregates["cache_write_tokens"] or 0,
            total_billable_tokens=aggregates["total_billable_tokens"] or 0,
            total_observed_tokens=aggregates["total_observed_tokens"] or 0,
        )

    def daily_summaries(
        self,
        *,
        start_date: date,
        end_date: date,
        supplier_name: str | None = None,
        model_name: str | None = None,
        operation_key: str | None = None,
    ) -> list[LLMUsageDaySummary]:
        """Return per-day usage totals for a date range."""

        queryset = self._filtered_queryset(
            start_date=start_date,
            end_date=end_date,
            supplier_name=supplier_name,
            model_name=model_name,
            operation_key=operation_key,
        )
        rows = (
            queryset.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(
                event_count=Count("id"),
                input_tokens=Sum("input_tokens"),
                cached_input_tokens=Sum("cached_input_tokens"),
                output_tokens=Sum("output_tokens"),
                cache_write_tokens=Sum("cache_write_tokens"),
                total_billable_tokens=Sum("total_billable_tokens"),
                total_observed_tokens=Sum("total_observed_tokens"),
            )
            .order_by("day")
        )
        return [
            LLMUsageDaySummary(
                day=row["day"],
                event_count=row["event_count"] or 0,
                input_tokens=row["input_tokens"] or 0,
                cached_input_tokens=row["cached_input_tokens"] or 0,
                output_tokens=row["output_tokens"] or 0,
                cache_write_tokens=row["cache_write_tokens"] or 0,
                total_billable_tokens=row["total_billable_tokens"] or 0,
                total_observed_tokens=row["total_observed_tokens"] or 0,
            )
            for row in rows
        ]

    def _filtered_queryset(
        self,
        *,
        day: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        supplier_name: str | None = None,
        model_name: str | None = None,
        operation_key: str | None = None,
    ):
        """Apply canonical date and identity filters to usage events."""

        queryset = LLMUsageEvent.objects.all()
        if day is not None:
            queryset = queryset.filter(created_at__date=day)
        if start_date is not None:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date is not None:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if supplier_name is not None:
            queryset = queryset.filter(supplier_name=supplier_name)
        if model_name is not None:
            queryset = queryset.filter(model_name=model_name)
        if operation_key is not None:
            queryset = queryset.filter(operation_key=operation_key)
        return queryset
