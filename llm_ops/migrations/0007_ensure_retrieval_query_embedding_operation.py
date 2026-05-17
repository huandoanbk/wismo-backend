from django.db import migrations


def ensure_retrieval_query_embedding_operation(apps, schema_editor):
    LLMOperation = apps.get_model("llm_ops", "LLMOperation")

    operation, _ = LLMOperation.objects.get_or_create(
        code="retrieval_query_embedding",
        defaults={
            "description": "Retrieval Query Embedding",
            "is_active": True,
        },
    )

    update_fields = []
    if operation.description != "Retrieval Query Embedding":
        operation.description = "Retrieval Query Embedding"
        update_fields.append("description")
    if not operation.is_active:
        operation.is_active = True
        update_fields.append("is_active")
    if update_fields:
        update_fields.append("updated_at")
        operation.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("llm_ops", "0006_alter_llmoperationconfig_operation_key"),
    ]

    operations = [
        migrations.RunPython(
            ensure_retrieval_query_embedding_operation,
            migrations.RunPython.noop,
        ),
    ]
