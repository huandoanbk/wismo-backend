"""Database router for vector-backed knowledge models."""

from __future__ import annotations


class VectorRouter:
    """Route knowledge vector models to the dedicated vector database."""

    VECTOR_MODELS = {"sourcedocument", "contentchunk", "chunkembedding"}
    KNOWN_DATABASES = {"default", "vector"}

    def db_for_read(self, model, **hints) -> str:
        """Return the correct database alias for model reads."""

        if model._meta.model_name in self.VECTOR_MODELS:
            return "vector"
        return "default"

    def db_for_write(self, model, **hints) -> str:
        """Return the correct database alias for model writes."""

        if model._meta.model_name in self.VECTOR_MODELS:
            return "vector"
        return "default"

    def allow_relation(self, obj1, obj2, **hints) -> bool | None:
        """Allow relations only when both objects live on the same known database."""

        db1 = getattr(obj1._state, "db", None)
        db2 = getattr(obj2._state, "db", None)
        if db1 in self.KNOWN_DATABASES and db2 in self.KNOWN_DATABASES:
            return db1 == db2
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints) -> bool:
        """Restrict vector models to the vector database and everything else to default."""

        if model_name in self.VECTOR_MODELS:
            return db == "vector"
        return db == "default"
