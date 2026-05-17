from django.db import migrations


def seed_guest_session_policy(apps, schema_editor):
    RuntimeConfig = apps.get_model("admin_config", "RuntimeConfig")
    RuntimeConfig.objects.get_or_create(
        key="guest.session_policy",
        defaults={
            "value": {"idle_ttl_hours": 6},
            "description": "Guest session idle TTL in hours. Session expires if no activity within this window.",
            "is_active": True,
        },
    )


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("admin_config", "0003_seed_step_trace_runtime_config"),
    ]

    operations = [
        migrations.RunPython(seed_guest_session_policy, noop_reverse),
    ]
