from django.db import migrations


def seed_prompt_assembly_policy(apps, schema_editor):
    RuntimeConfig = apps.get_model("admin_config", "RuntimeConfig")
    RuntimeConfig.objects.get_or_create(
        key="runtime.prompt_assembly",
        defaults={
            "value": {"max_estimated_tokens": 3500},
            "description": "Prompt assembly compaction threshold in estimated tokens. Compact triggers when prompt exceeds this limit.",
            "is_active": True,
        },
    )


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("admin_config", "0005_seed_admin_contact_email"),
    ]

    operations = [
        migrations.RunPython(seed_prompt_assembly_policy, noop_reverse),
    ]
