from django.db import migrations


def seed_admin_contact_email(apps, schema_editor):
    RuntimeConfig = apps.get_model("admin_config", "RuntimeConfig")
    RuntimeConfig.objects.get_or_create(
        key="admin.contact_email",
        defaults={
            "value": {"email": ""},
            "description": "Destination email address for contact form submissions.",
            "is_active": True,
        },
    )


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("admin_config", "0004_seed_guest_session_policy"),
    ]

    operations = [
        migrations.RunPython(seed_admin_contact_email, noop_reverse),
    ]
