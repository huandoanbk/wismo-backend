from django.db import migrations


def ensure_triage_classifier_operation(apps, schema_editor):
    LLMOperation = apps.get_model("llm_ops", "LLMOperation")
    operation, _ = LLMOperation.objects.get_or_create(
        code="triage_classifier",
        defaults={
            "description": "Triage Classifier",
            "is_active": True,
        },
    )
    update_fields = []
    if operation.description != "Triage Classifier":
        operation.description = "Triage Classifier"
        update_fields.append("description")
    if not operation.is_active:
        operation.is_active = True
        update_fields.append("is_active")
    if update_fields:
        update_fields.append("updated_at")
        operation.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("llm_ops", "0003_llmgatewayconfig_llmoperation_and_backfill"),
    ]

    operations = [
        migrations.RunPython(
            ensure_triage_classifier_operation,
            migrations.RunPython.noop,
        ),
    ]
