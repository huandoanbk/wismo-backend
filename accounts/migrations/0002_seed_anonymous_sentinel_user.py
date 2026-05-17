"""Seed the Anonymous Sentinel user used as owner of anonymized GDPR data."""

from __future__ import annotations

from django.db import migrations

ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000001"


def seed_anonymous_sentinel(apps, schema_editor):
    """Create the Anonymous Sentinel user if it does not already exist."""

    User = apps.get_model("accounts", "User")
    User.objects.get_or_create(
        id=ANONYMOUS_USER_ID,
        defaults={
            "email": "anonymous@system.internal",
            "display_name": "Anonymous",
            "is_active": False,
            "email_verified": False,
            "is_staff": False,
            "is_superuser": False,
        },
    )


def remove_anonymous_sentinel(apps, schema_editor):
    """Remove the sentinel user (only used when reversing migration in dev)."""

    User = apps.get_model("accounts", "User")
    User.objects.filter(id=ANONYMOUS_USER_ID).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            seed_anonymous_sentinel,
            reverse_code=remove_anonymous_sentinel,
        ),
    ]
