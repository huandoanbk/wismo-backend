"""Identity models for the MVP backend foundation."""

from __future__ import annotations

import uuid
from typing import Any

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Manager for the canonical registered user model."""

    use_in_migrations = True

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """Create and persist a regular user with email as username."""

        if not email:
            raise ValueError("The email field must be set.")

        user = self.model(email=self.normalize_email(email), **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """Create and persist a Django superuser."""

        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        if not password:
            raise ValueError("Superuser must have a password.")

        return self.create_user(email=email, password=password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Registered identity used for durable MVP continuity."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    display_name = models.CharField(max_length=255, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    google_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    email_verified = models.BooleanField(default=False)
    email_otp_hash = models.CharField(max_length=255, null=True, blank=True)
    email_otp_expires_at = models.DateTimeField(null=True, blank=True)
    email_otp_sent_at = models.DateTimeField(null=True, blank=True)
    resend_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:
        """Return a stable human-readable identity label."""

        return self.email


class GuestIdentity(models.Model):
    """Ephemeral guest identity that can own chats before account creation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=64, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    pending_input_text = models.TextField(blank=True)
    pending_input_append_count = models.PositiveSmallIntegerField(default=0)
    pending_input_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "guest_identities"
        indexes = [
            models.Index(fields=["is_active", "last_seen_at"], name="idx_guest_active_seen"),
        ]

    def mark_seen(self) -> None:
        """Refresh last activity and extend sliding idle TTL."""

        from datetime import timedelta

        from runtime.services import RuntimeConfigService

        now = timezone.now()
        self.last_seen_at = now
        ttl_hours = RuntimeConfigService().guest_session_policy().idle_ttl_hours
        self.expires_at = now + timedelta(hours=ttl_hours)
        self.save(update_fields=["last_seen_at", "expires_at"])
