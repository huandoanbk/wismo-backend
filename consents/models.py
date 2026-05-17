"""Consent persistence for registered and guest identities."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class ConsentRecord(models.Model):
    """Audit-friendly consent record required before chat runtime starts."""

    CURRENT_VERSION = "v1.0"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="consent_records",
    )
    guest_identity = models.ForeignKey(
        "accounts.GuestIdentity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="consent_records",
    )
    consent_version = models.CharField(max_length=20, default=CURRENT_VERSION)
    is_accepted = models.BooleanField(default=True)
    accepted_at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    reconsent_required = models.BooleanField(default=False)

    class Meta:
        db_table = "consent_records"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(user__isnull=False) & Q(guest_identity__isnull=True))
                    | (Q(user__isnull=True) & Q(guest_identity__isnull=False))
                ),
                name="consent_exactly_one_owner",
            )
        ]
        indexes = [
            models.Index(fields=["user", "-accepted_at"], name="idx_consent_user_latest"),
            models.Index(fields=["guest_identity", "-accepted_at"], name="idx_consent_guest_latest"),
        ]

    @classmethod
    def has_active_consent(
        cls,
        *,
        user=None,
        guest_identity=None,
    ) -> bool:
        """Return whether the identity has a current accepted consent record."""
        from consents.services import ConsentService

        return ConsentService().has_active_consent(user=user, guest_identity=guest_identity)
