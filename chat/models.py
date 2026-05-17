"""Chat, case, and turn persistence for the MVP backend foundation."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

from wismo.contracts.enums import (
    CasePhase,
    CaseStatus,
    ResponseMethod,
    Step12FinalizationStatus,
    TriageDecision,
    TurnStatus,
    UsageAccountingStatus,
)


def enum_choices(enum_cls: type) -> list[tuple[str, str]]:
    """Build Django choices from a string enum."""

    return [(member.value, member.name) for member in enum_cls]


class Case(models.Model):
    """Backend continuity object for one user problem across chats."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="cases",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="cases",
    )
    topic = models.CharField(max_length=200, blank=True)
    context_summary = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=enum_choices(CaseStatus),
        default=CaseStatus.ACTIVE.value,
    )
    phase = models.CharField(
        max_length=20,
        choices=enum_choices(CasePhase),
        default=CasePhase.UNDERSTAND.value,
    )
    last_activity_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cases"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(user__isnull=False) & Q(guest_identity__isnull=True))
                    | (Q(user__isnull=True) & Q(guest_identity__isnull=False))
                ),
                name="case_exactly_one_owner",
            )
        ]
        indexes = [
            models.Index(fields=["user", "-last_activity_at"], name="idx_case_user_activity"),
            models.Index(fields=["guest_identity", "-last_activity_at"], name="idx_case_guest_activity"),
        ]

    def touch(self) -> None:
        """Refresh the case activity timestamp."""

        self.last_activity_at = timezone.now()
        self.save(update_fields=["last_activity_at"])


class Chat(models.Model):
    """Frontend thread object; users primarily interact with chat_id."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="chats",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="chats",
    )
    case = models.ForeignKey(
        "chat.Case",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="chats",
    )
    chat_display_name = models.CharField(max_length=120, default="New chat")
    opening_input_text = models.TextField(blank=True)
    is_pending_case_confirmation = models.BooleanField(default=False)
    pending_confirm_turn_count = models.PositiveSmallIntegerField(default=0)
    is_archived = models.BooleanField(default=False)
    disabled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "chats"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(user__isnull=False) & Q(guest_identity__isnull=True))
                    | (Q(user__isnull=True) & Q(guest_identity__isnull=False))
                ),
                name="chat_exactly_one_owner",
            )
        ]
        indexes = [
            models.Index(fields=["user", "-last_activity_at"], name="idx_chat_user_activity"),
            models.Index(fields=["guest_identity", "-last_activity_at"], name="idx_chat_guest_activity"),
        ]

    def touch(self) -> None:
        """Refresh the chat activity timestamp."""

        self.last_activity_at = timezone.now()
        self.save(update_fields=["last_activity_at"])


class ChatTurn(models.Model):
    """One user input and final assistant response in a chat."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey("chat.Chat", on_delete=models.CASCADE, related_name="turns")
    case = models.ForeignKey(
        "chat.Case",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="turns",
    )
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="chat_turns",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="chat_turns",
    )
    user_message_text = models.TextField()
    assistant_response_text = models.TextField(blank=True)
    response_method = models.CharField(
        max_length=40,
        choices=enum_choices(ResponseMethod),
        default=ResponseMethod.ASK.value,
    )
    triage_decision = models.CharField(
        max_length=80,
        choices=enum_choices(TriageDecision),
        default=TriageDecision.CONTINUE_TO_FULL_REASONING.value,
    )
    status = models.CharField(
        max_length=20,
        choices=enum_choices(TurnStatus),
        default=TurnStatus.RECEIVED.value,
    )
    runtime_metadata = models.JSONField(default=dict)
    input_tokens = models.PositiveIntegerField(default=0)
    cached_input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    total_billable_tokens = models.PositiveIntegerField(default=0)
    total_observed_tokens = models.PositiveIntegerField(default=0)
    quota_window_before = models.JSONField(null=True, blank=True)
    quota_window_after = models.JSONField(null=True, blank=True)
    quota_exhausted_after_turn = models.BooleanField(default=False)
    usage_accounting_status = models.CharField(
        max_length=20,
        choices=enum_choices(UsageAccountingStatus),
        default=UsageAccountingStatus.PENDING.value,
    )
    step12_finalization_status = models.CharField(
        max_length=20,
        choices=enum_choices(Step12FinalizationStatus),
        default=Step12FinalizationStatus.PENDING.value,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "chat_turns"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(user__isnull=False) & Q(guest_identity__isnull=True))
                    | (Q(user__isnull=True) & Q(guest_identity__isnull=False))
                ),
                name="turn_exactly_one_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["chat", "-created_at"], name="idx_turn_chat_created"),
            models.Index(fields=["status", "created_at"], name="idx_turn_status_created"),
        ]

    def mark_completed(self, response_text: str, response_method: ResponseMethod) -> None:
        """Persist the final response and mark the turn completed."""

        self.assistant_response_text = response_text
        self.response_method = response_method.value
        self.status = TurnStatus.COMPLETED.value
        self.finalized_at = timezone.now()
        self.save(
            update_fields=[
                "assistant_response_text",
                "response_method",
                "status",
                "finalized_at",
            ]
        )
