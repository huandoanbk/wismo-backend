"""Admin registration for memory models."""

from django.contrib import admin

from memory.models import MemoryItem, UserPreferenceState, UserProfileState, UserStateSnapshot


@admin.register(MemoryItem)
class MemoryItemAdmin(admin.ModelAdmin):
    """Admin view for long-term memory items."""

    list_display = ("id", "user", "guest_identity", "case", "memory_type", "is_active", "created_at")
    list_filter = ("memory_type", "is_active")
    search_fields = ("normalized_text",)


@admin.register(UserProfileState)
class UserProfileStateAdmin(admin.ModelAdmin):
    """Admin view for identity-scoped profile state."""

    list_display = ("id", "user", "guest_identity", "version", "updated_at")
    search_fields = ("id",)


@admin.register(UserPreferenceState)
class UserPreferenceStateAdmin(admin.ModelAdmin):
    """Admin view for identity-scoped preference state."""

    list_display = ("id", "user", "guest_identity", "updated_at")
    search_fields = ("id",)


@admin.register(UserStateSnapshot)
class UserStateSnapshotAdmin(admin.ModelAdmin):
    """Admin view for identity-scoped state snapshot."""

    list_display = ("id", "user", "guest_identity", "primary_state", "secondary_state", "updated_at")
    list_filter = ("primary_state",)
    search_fields = ("id",)
