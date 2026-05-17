from django.db import migrations


def ensure_step5_case_operations(apps, schema_editor):
    LLMOperation = apps.get_model("llm_ops", "LLMOperation")

    required = (
        ("case_detector", "Case Detector"),
        ("case_reresolution_classifier", "Case Reresolution Classifier"),
    )
    for code, description in required:
        operation, _ = LLMOperation.objects.get_or_create(
            code=code,
            defaults={
                "description": description,
                "is_active": True,
            },
        )
        update_fields = []
        if operation.description != description:
            operation.description = description
            update_fields.append("description")
        if not operation.is_active:
            operation.is_active = True
            update_fields.append("is_active")
        if update_fields:
            update_fields.append("updated_at")
            operation.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("llm_ops", "0004_ensure_triage_classifier_operation"),
    ]

    operations = [
        migrations.RunPython(
            ensure_step5_case_operations,
            migrations.RunPython.noop,
        ),
    ]
