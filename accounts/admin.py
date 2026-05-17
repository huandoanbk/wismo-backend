"""Admin registration for account foundation models."""

from django.contrib import admin

from accounts.models import GuestIdentity, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Minimal admin view for registered users."""

    list_display = ("email", "email_verified", "is_active", "is_staff", "date_joined")
    search_fields = ("email", "display_name")
    ordering = ("-date_joined",)


@admin.register(GuestIdentity)
class GuestIdentityAdmin(admin.ModelAdmin):
    """Minimal admin view for guest identities."""

    list_display = ("id", "is_active", "created_at", "last_seen_at", "expires_at")
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)
