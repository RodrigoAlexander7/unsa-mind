from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbedderPort(Protocol):
    dimension: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...
