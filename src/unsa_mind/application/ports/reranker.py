from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from unsa_mind.domain.entities import ScoredChunk


class RerankerPort(Protocol):
    async def rerank(
        self, query: str, candidates: Sequence[ScoredChunk], top_n: int
    ) -> list[ScoredChunk]: ...
