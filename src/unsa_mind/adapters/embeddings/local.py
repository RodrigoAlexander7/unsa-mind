"""Embeddings locales con sentence-transformers (extra opcional `local-embeddings`)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from ._http import EmbeddingError, check_dimension

DEFAULT_MODEL = "BAAI/bge-m3"


class LocalEmbedder:
    def __init__(
        self, *, model: str | None = None, dimension: int = 1024, st_model: Any = None
    ) -> None:
        self.model_name = model or DEFAULT_MODEL
        self.dimension = dimension
        self._model = st_model  # inyectable en tests; si no, se carga perezosamente
        self._lock = asyncio.Lock()

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    "El embedder 'local' requiere sentence-transformers: "
                    "pip install 'unsa-mind[local-embeddings]'"
                ) from exc
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        out = [[float(x) for x in v] for v in vecs]
        check_dimension(out, self.dimension, f"El modelo {self.model_name}")
        return out

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        async with self._lock:  # un solo encode a la vez: el modelo no es thread-safe
            return await asyncio.to_thread(self._encode, list(texts))

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]
