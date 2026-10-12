"""Embedders: Gemini, OpenAI-compatible, local (sentence-transformers)."""

from ._http import EmbeddingError
from .factory import build_embedder

__all__ = ["EmbeddingError", "build_embedder"]
