"""Admin registration for knowledge models."""

from django.contrib import admin

from knowledge.models import ChunkEmbedding, ContentChunk, SourceDocument


@admin.register(SourceDocument)
class SourceDocumentAdmin(admin.ModelAdmin):
    """Read-only admin view for legacy source metadata in vector DB."""

    change_list_template = "admin/knowledge/sourcedocument/change_list.html"
    list_display = (
        "id",
        "title",
        "speaker_or_author",
        "source_type",
        "source_kind",
        "language",
        "is_enabled",
        "total_chunks",
        "ingested_at",
        "updated_at",
    )
    list_filter = ("source_type", "source_kind", "language", "is_enabled")
    search_fields = ("title", "speaker_or_author", "source_url", "file_hash", "id")
    readonly_fields = [field.name for field in SourceDocument._meta.fields]
    ordering = ("-updated_at", "-created_at")

    def changelist_view(self, request, extra_context=None):
        """Add cross-table summary counts for quick corpus health checks."""

        extra = extra_context or {}
        extra["knowledge_summary"] = {
            "documents": SourceDocument.objects.count(),
            "chunks": ContentChunk.objects.count(),
            "embeddings": ChunkEmbedding.objects.count(),
            "active_documents": SourceDocument.objects.filter(is_enabled=True).count(),
            "active_chunks": ContentChunk.objects.filter(state=ContentChunk.STATE_ACTIVE).count(),
        }
        return super().changelist_view(request, extra_context=extra)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ContentChunk)
class ContentChunkAdmin(admin.ModelAdmin):
    """Read-only admin view for legacy retrieval chunks."""

    list_display = (
        "id",
        "source_document",
        "segment_index",
        "language",
        "token_count",
        "topic",
        "content_type",
        "depth_level",
        "state",
        "content_preview",
        "created_at",
    )
    list_filter = ("language", "content_type", "depth_level", "state")
    search_fields = ("id", "source_document__id", "topic", "content_hash", "sha256_checksum", "content_text")
    readonly_fields = [field.name for field in ContentChunk._meta.fields]
    ordering = ("source_document_id", "segment_index")

    @admin.display(description="Content Preview")
    def content_preview(self, obj: ContentChunk) -> str:
        text = (obj.content_text or "").strip().replace("\n", " ")
        return text[:160]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChunkEmbedding)
class ChunkEmbeddingAdmin(admin.ModelAdmin):
    """Read-only admin view for legacy chunk embeddings."""

    list_display = ("id", "chunk", "embedding_model", "model_name", "chunking_version", "embedded_at", "created_at")
    list_filter = ("embedding_model", "chunking_version")
    search_fields = ("id", "chunk__id", "model_name", "embedding_model")
    readonly_fields = (
        "id",
        "chunk",
        "embedding_model",
        "model_name",
        "chunking_version",
        "embedded_at",
        "created_at",
        "embedding_dimensions",
    )
    fields = readonly_fields
    ordering = ("-created_at",)

    @admin.display(description="Embedding Dimensions")
    def embedding_dimensions(self, obj: ChunkEmbedding) -> int | str:
        """Return vector length without rendering raw vector payload."""

        value = getattr(obj, "embedding", None)
        if value is None:
            return "-"
        try:
            return len(value)
        except Exception:
            return "-"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
