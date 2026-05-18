"""Memory persistence for synchronous post-turn consolidation."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q


class MemoryItem(models.Model):
    """Case-scoped long-term memory extracted from safe conversational turns."""
    SEGMENT_STATUS_CHOICES = [
        ("active", "active"),
        ("closed", "closed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="memory_items",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="memory_items",
    )
    case = models.ForeignKey(
        "chat.Case",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="memory_items",
    )
    start_turn = models.ForeignKey(
        "chat.ChatTurn",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="memory_segment_start_items",
    )
    end_turn = models.ForeignKey(
        "chat.ChatTurn",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="memory_segment_end_items",
    )
    segment_status = models.CharField(max_length=16, choices=SEGMENT_STATUS_CHOICES, default="active")
    user_concern_summary = models.TextField(blank=True, default="")
    assistant_approach_summary = models.TextField(blank=True, default="")
    user_response_summary = models.TextField(blank=True, default="")
    state_shift = models.TextField(blank=True, default="")
    open_loops = models.JSONField(default=list)
    confidence = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "memory_items"
        indexes = [
            models.Index(fields=["user", "case", "segment_status"], name="idx_memory_user_case_status"),
            models.Index(fields=["guest_identity", "case", "segment_status"], name="idx_memory_guest_case_status"),
        ]


class UserProfileState(models.Model):
    """Identity-scoped profile facts extracted from prior turns."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="profile_states",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="profile_states",
    )
    profile_data = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_profile_states"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(user__isnull=False) & Q(guest_identity__isnull=True))
                    | (Q(user__isnull=True) & Q(guest_identity__isnull=False))
                ),
                name="profile_state_exactly_one_owner",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(user__isnull=False, guest_identity__isnull=True),
                name="uq_profile_state_user_owner",
            ),
            models.UniqueConstraint(
                fields=["guest_identity"],
                condition=Q(guest_identity__isnull=False, user__isnull=True),
                name="uq_profile_state_guest_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-updated_at"], name="idx_profile_state_user"),
            models.Index(fields=["guest_identity", "-updated_at"], name="idx_profile_state_guest"),
        ]


class UserPreferenceState(models.Model):
    """Identity-scoped preference profile with evidence counters."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="preference_states",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="preference_states",
    )
    preference_data = models.JSONField(default=dict)
    evidence_counts = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_preference_states"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(user__isnull=False) & Q(guest_identity__isnull=True))
                    | (Q(user__isnull=True) & Q(guest_identity__isnull=False))
                ),
                name="preference_state_exactly_one_owner",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(user__isnull=False, guest_identity__isnull=True),
                name="uq_preference_state_user_owner",
            ),
            models.UniqueConstraint(
                fields=["guest_identity"],
                condition=Q(guest_identity__isnull=False, user__isnull=True),
                name="uq_preference_state_guest_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-updated_at"], name="idx_preference_state_user"),
            models.Index(fields=["guest_identity", "-updated_at"], name="idx_preference_state_guest"),
        ]


class UserStateSnapshot(models.Model):
    """Identity-scoped user state inferred from runtime signals."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="state_snapshots",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="state_snapshots",
    )
    primary_state = models.CharField(max_length=80, blank=True)
    secondary_state = models.CharField(max_length=80, blank=True)
    raw_signals = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_state_snapshots"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(user__isnull=False) & Q(guest_identity__isnull=True))
                    | (Q(user__isnull=True) & Q(guest_identity__isnull=False))
                ),
                name="state_snapshot_exactly_one_owner",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(user__isnull=False, guest_identity__isnull=True),
                name="uq_state_snapshot_user_owner",
            ),
            models.UniqueConstraint(
                fields=["guest_identity"],
                condition=Q(guest_identity__isnull=False, user__isnull=True),
                name="uq_state_snapshot_guest_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-updated_at"], name="idx_state_snapshot_user"),
            models.Index(fields=["guest_identity", "-updated_at"], name="idx_state_snapshot_guest"),
        ]
