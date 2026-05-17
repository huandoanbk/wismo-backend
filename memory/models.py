"""Memory persistence for synchronous post-turn consolidation."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from pgvector.django import VectorField


class MemoryItem(models.Model):
    """Case-scoped long-term memory extracted from safe conversational turns."""

    MEMORY_TYPE_CHOICES = [
        ("theme", "theme"),
        ("trigger", "trigger"),
        ("coping", "coping"),
        ("profile_fact", "profile_fact"),
        ("preference", "preference"),
        ("state_pattern", "state_pattern"),
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
    evidence_turn = models.ForeignKey(
        "chat.ChatTurn",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="memory_evidence_items",
    )
    memory_type = models.CharField(max_length=40, choices=MEMORY_TYPE_CHOICES)
    normalized_text = models.TextField()
    confidence = models.FloatField(default=0.0)
    evidence_count = models.PositiveIntegerField(default=1)
    embedding = VectorField(dimensions=1024, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "memory_items"
        indexes = [
            models.Index(fields=["user", "case", "is_active"], name="idx_memory_user_case"),
            models.Index(fields=["guest_identity", "case", "is_active"], name="idx_memory_guest_case"),
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
