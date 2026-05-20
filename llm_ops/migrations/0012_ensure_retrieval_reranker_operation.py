from django.db import migrations


def ensure_retrieval_reranker_operation(apps, schema_editor):
    LLMOperation = apps.get_model("llm_ops", "LLMOperation")

    operation, _ = LLMOperation.objects.get_or_create(
        code="retrieval_reranker",
        defaults={
            "description": "Retrieval Reranker",
            "is_active": True,
        },
    )

    update_fields = []
    if operation.description != "Retrieval Reranker":
        operation.description = "Retrieval Reranker"
        update_fields.append("description")
    if not operation.is_active:
        operation.is_active = True
        update_fields.append("is_active")
    if update_fields:
        update_fields.append("updated_at")
        operation.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("llm_ops", "0011_alter_llmgatewayconfig_integration_kind"),
    ]

    operations = [
        migrations.RunPython(
            ensure_retrieval_reranker_operation,
            migrations.RunPython.noop,
        ),
    ]
