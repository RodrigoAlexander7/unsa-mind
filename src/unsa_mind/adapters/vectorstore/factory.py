from __future__ import annotations

from unsa_mind.adapters.memory import InMemoryVectorStore
from unsa_mind.application.ports import EmbedderPort, VectorStorePort
from unsa_mind.config.settings import Settings

from .sqlite_store import DB_FILENAME, SqliteVectorStore


def embedder_id(settings: Settings) -> str:
    return f"{settings.embedder_provider}:{settings.embedder_model or 'default'}"


def build_vector_store(settings: Settings, embedder: EmbedderPort) -> VectorStorePort:
    kind = settings.vector_store
    if kind == "memory":
        return InMemoryVectorStore()
    if kind == "sqlite":
        return SqliteVectorStore(
            settings.data_dir / DB_FILENAME,
            embedder.dimension,
            embedder_id=embedder_id(settings),
        )
    if kind == "qdrant":
        from .qdrant_store import QdrantVectorStore  # import perezoso (extra opcional)

        return QdrantVectorStore(
            embedder.dimension,
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection=settings.qdrant_collection,
        )
    raise ValueError(f"Vector store desconocido: {kind!r}")
