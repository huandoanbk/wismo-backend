"""Read-only knowledge models mapped to the legacy vector-database schema."""

from __future__ import annotations

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models
from pgvector.django import VectorField


class SourceDocument(models.Model):
    """Legacy source document metadata stored in the vector database."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_type = models.CharField(max_length=80)
    source_kind = models.CharField(max_length=80)
    source_format = models.CharField(max_length=80, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    speaker_or_author = models.CharField(max_length=255, blank=True, null=True, db_column="author")
    language = models.CharField(max_length=20, blank=True, null=True)
    file_hash = models.CharField(max_length=255, blank=True, null=True)
    source_url = models.CharField(max_length=500, blank=True, null=True)
    metadata = models.JSONField(default=dict, db_column="type_metadata")
    topic_tags = models.JSONField(default=list, blank=True)
    total_chunks = models.IntegerField(blank=True, null=True)
    is_enabled = models.BooleanField(blank=True, null=True, db_column="is_active")
    ingested_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "source_documents"
        managed = False

    def __str__(self) -> str:
        """Return a compact operator-facing label."""

        return self.title or str(self.id)


class ContentChunk(models.Model):
    """Legacy retrievable chunk rows stored in the vector database."""

    STATE_ACTIVE = "active"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_document = models.ForeignKey(
        "knowledge.SourceDocument",
        on_delete=models.CASCADE,
        related_name="chunks",
        db_column="source_id",
    )
    segment_index = models.PositiveIntegerField(db_column="chunk_index")
    content_text = models.TextField(db_column="content")
    language = models.CharField(max_length=20, blank=True, null=True)
    token_count = models.IntegerField(blank=True, null=True)
    topic = models.CharField(max_length=255, blank=True, null=True)
    content_type = models.CharField(max_length=255, blank=True, null=True, db_column="teaching_type")
    dharma_concepts = ArrayField(
        models.TextField(),
        blank=True,
        null=True,
        db_column="applicable_issues",
    )
    depth_level = models.CharField(max_length=80, blank=True, null=True)
    emotional_tone = models.CharField(max_length=80, blank=True, null=True)
    state = models.CharField(max_length=40, blank=True, null=True)
    content_hash = models.CharField(max_length=255, blank=True, null=True)
    sha256_checksum = models.CharField(max_length=255)
    chunking_version = models.CharField(max_length=120, blank=True, null=True)
    enrichment_version = models.CharField(max_length=120, blank=True, null=True)
    embedding_version = models.CharField(max_length=120, blank=True, null=True)
    processing_version = models.CharField(max_length=120, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "content_chunks"
        managed = False

    @property
    def is_enabled(self) -> bool:
        """Compatibility flag used by retrieval/admin code paths."""

        return self.state == self.STATE_ACTIVE


class ChunkEmbedding(models.Model):
    """Legacy vector embedding row for one content chunk."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chunk = models.OneToOneField(
        "knowledge.ContentChunk",
        on_delete=models.CASCADE,
        related_name="embedding_record",
        db_column="chunk_id",
    )
    embedding = VectorField(dimensions=1024)
    model_name = models.CharField(max_length=120, blank=True, null=True)
    embedding_model = models.CharField(max_length=120)
    chunking_version = models.CharField(max_length=120)
    embedded_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "chunk_embeddings"
        managed = False
