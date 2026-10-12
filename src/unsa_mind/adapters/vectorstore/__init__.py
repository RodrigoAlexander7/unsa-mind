"""Almacenes vectoriales persistentes (SQLite, Qdrant opcional)."""

from .factory import build_vector_store
from .sqlite_store import SqliteVectorStore, VectorIndexMismatchError

__all__ = ["SqliteVectorStore", "VectorIndexMismatchError", "build_vector_store"]
