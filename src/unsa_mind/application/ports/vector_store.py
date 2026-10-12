from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from unsa_mind.domain.entities import Chunk, ScoredChunk


class VectorStorePort(Protocol):
    """Índice híbrido. La fusión denso+léxico (RRF) es responsabilidad del adaptador."""

    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None: ...

    async def deactivate_document(self, doc_id: str) -> int:
        """Marca como inactivos (no se borran) los chunks de un documento. Devuelve cuántos."""
        ...

    async def search(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        k: int = 20,
        filters: dict[str, Any] | None = None,  # solo chunks activos; filtros por metadata
    ) -> list[ScoredChunk]: ...

    async def count(self, *, active_only: bool = True) -> int: ...
