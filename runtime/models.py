"""Runtime support models for quota and turn gating."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class UsageQuotaWindow(models.Model):
    """Token quota state for one identity and time window."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="quota_windows",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="quota_windows",
    )
    window_started_at = models.DateTimeField(default=timezone.now)
    window_ends_at = models.DateTimeField(null=True, blank=True)
    token_limit = models.PositiveIntegerField(default=50000)
    used_tokens = models.PositiveIntegerField(default=0)
    is_exhausted = models.BooleanField(default=False)
    pending_input_text = models.TextField(blank=True)
    pending_input_append_count = models.PositiveSmallIntegerField(default=0)
    pending_input_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "usage_quota_windows"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(user__isnull=False) & Q(guest_identity__isnull=True))
                    | (Q(user__isnull=True) & Q(guest_identity__isnull=False))
                ),
                name="quota_exactly_one_owner",
            )
        ]
        indexes = [
            models.Index(fields=["user", "-window_started_at"], name="idx_quota_user_window"),
            models.Index(fields=["guest_identity", "-window_started_at"], name="idx_quota_guest_window"),
        ]

    @classmethod
    def current_for_identity(cls, *, user=None, guest_identity=None) -> UsageQuotaWindow:
        """Return the current quota window, creating a foundation default if absent."""

        from runtime.services import QuotaService

        return QuotaService().current_for_identity(user=user, guest_identity=guest_identity)

    def snapshot(self) -> dict[str, int | bool | str]:
        """Return a small serializable quota snapshot."""

        return {
            "quota_window_id": str(self.id),
            "used_tokens": self.used_tokens,
            "token_limit": self.token_limit,
            "is_exhausted": self.is_exhausted,
        }

    def append_pending_input(self, message: str, max_appends: int = 10, max_chars: int = 12000) -> None:
        """Store blocked input for quota recovery UX without entering runtime."""

        if self.pending_input_append_count >= max_appends:
            return

        separator = "\n\n" if self.pending_input_text else ""
        self.pending_input_text = f"{self.pending_input_text}{separator}{message}"[:max_chars]
        self.pending_input_append_count += 1
        self.pending_input_updated_at = timezone.now()
        self.save(
            update_fields=[
                "pending_input_text",
                "pending_input_append_count",
                "pending_input_updated_at",
                "updated_at",
            ]
        )

    def consume_tokens(self, tokens: int) -> None:
        """Add billable tokens and update exhaustion state."""

        self.used_tokens += max(tokens, 0)
        self.is_exhausted = self.used_tokens >= self.token_limit
        self.save(update_fields=["used_tokens", "is_exhausted", "updated_at"])


class OperationalLog(models.Model):
    """Persist operational events for runtime/gateway diagnostics."""

    LEVEL_INFO = "info"
    LEVEL_WARNING = "warning"
    LEVEL_ERROR = "error"
    LEVEL_CRITICAL = "critical"
    LEVEL_CHOICES = (
        (LEVEL_INFO, "INFO"),
        (LEVEL_WARNING, "WARNING"),
        (LEVEL_ERROR, "ERROR"),
        (LEVEL_CRITICAL, "CRITICAL"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default=LEVEL_ERROR)
    event_key = models.CharField(max_length=120)
    component = models.CharField(max_length=120, blank=True)
    message = models.TextField()
    context = models.JSONField(default=dict)
    turn = models.ForeignKey(
        "chat.ChatTurn",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="operational_logs",
    )
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="operational_logs",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="operational_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "operational_logs"
        indexes = [
            models.Index(fields=["event_key", "-created_at"], name="idx_op_log_event_time"),
            models.Index(fields=["level", "-created_at"], name="idx_op_log_level_time"),
            models.Index(fields=["component", "-created_at"], name="idx_op_log_component_time"),
        ]
