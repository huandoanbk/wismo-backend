"""Admin registration for consent records."""

from django.contrib import admin

from consents.models import ConsentRecord


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    """Minimal admin view for consent records."""

    list_display = ("id", "user", "guest_identity", "consent_version", "is_accepted", "accepted_at")
    list_filter = ("is_accepted", "consent_version")
    ordering = ("-accepted_at",)
