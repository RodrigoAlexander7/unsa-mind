"""Adaptadores en memoria: base de pruebas y modo sin dependencias externas."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import AsyncIterator, Sequence
from typing import Any

from unsa_mind.application.ports import ChatMessage
from unsa_mind.domain.entities import (
    Chunk,
    DocumentRecord,
    Schedule,
    ScoredChunk,
    Source,
    UpdateReport,
)

_TOKEN = re.compile(r"\w+", re.UNICODE)
_STOP = frozenset(
    "de la el en y a los las del que se por con para un una al es lo como su sus o u e".split()
)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in _TOKEN.findall(text) if t not in _STOP and len(t) > 1]


class HashingEmbedder:
    """Embedding determinista por hashing de tokens. Sin red ni modelos: sirve offline y en tests."""

    def __init__(self, dimension: int = 512) -> None:
        self.dimension = dimension

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dimension
        for tok in tokenize(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dimension] += 1.0 if (h >> 64) % 2 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class InMemoryVectorStore:
    """Búsqueda híbrida simple: coseno + solapamiento léxico fusionados (score en [0, 1])."""

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, list[float]] = {}

    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        for chunk, vec in zip(chunks, vectors, strict=True):
            self._chunks[chunk.id] = chunk
            self._vectors[chunk.id] = list(vec)

    async def deactivate_document(self, doc_id: str) -> int:
        n = 0
        for c in self._chunks.values():
            if c.doc_id == doc_id and c.active:
                c.active = False
                n += 1
        return n

    async def search(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        q_tokens = set(tokenize(query_text))
        scored: list[ScoredChunk] = []
        for cid, chunk in self._chunks.items():
            if not chunk.active:
                continue
            if filters and any(chunk.metadata.get(f) != v for f, v in filters.items()):
                continue
            dense = max(0.0, sum(a * b for a, b in zip(query_vector, self._vectors[cid])))
            doc_tokens = set(tokenize(chunk.indexable_text))
            lexical = len(q_tokens & doc_tokens) / len(q_tokens) if q_tokens else 0.0
            scored.append(ScoredChunk(chunk, 0.5 * dense + 0.5 * lexical))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]

    async def count(self, *, active_only: bool = True) -> int:
        return sum(1 for c in self._chunks.values() if c.active or not active_only)


class InMemorySourceRepository:
    def __init__(self) -> None:
        self._items: dict[str, Source] = {}

    async def list_sources(self, *, enabled_only: bool = False) -> list[Source]:
        return [s for s in self._items.values() if s.enabled or not enabled_only]

    async def get_source(self, source_id: str) -> Source | None:
        return self._items.get(source_id)

    async def save_source(self, source: Source) -> None:
        self._items[source.id] = source

    async def delete_source(self, source_id: str) -> None:
        self._items.pop(source_id, None)


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._items: dict[str, DocumentRecord] = {}

    async def get_active(self, url: str) -> DocumentRecord | None:
        return next((d for d in self._items.values() if d.url == url and d.active), None)

    async def save(self, record: DocumentRecord) -> None:
        self._items[record.doc_id] = record

    async def deactivate(self, doc_id: str) -> None:
        if doc_id in self._items:
            self._items[doc_id].active = False

    async def list_documents(self, *, active_only: bool = True) -> Sequence[DocumentRecord]:
        return [d for d in self._items.values() if d.active or not active_only]


class InMemorySettingsRepository:
    def __init__(self, schedule: Schedule | None = None) -> None:
        self._schedule = schedule or Schedule()
        self._saved = schedule is not None
        self._reports: list[UpdateReport] = []

    async def has_schedule(self) -> bool:
        return self._saved

    async def get_schedule(self) -> Schedule:
        return self._schedule

    async def save_schedule(self, schedule: Schedule) -> None:
        self._schedule = schedule
        self._saved = True

    async def save_report(self, report: UpdateReport) -> None:
        self._reports.insert(0, report)
        del self._reports[100:]

    async def list_reports(self, limit: int = 20) -> list[UpdateReport]:
        return self._reports[:limit]


class FakeLLM:
    """LLM de pruebas: devuelve un extracto del primer documento citando [1]."""

    name = "fake"

    def _answer(self, messages: Sequence[ChatMessage]) -> str:
        prompt = messages[-1].content
        m = re.search(r"\[1\][^\n]*\n(.+)", prompt)
        body = m.group(1).strip()[:300] if m else "Sin información."
        return f"Según la documentación oficial: {body} [1]"

    async def complete(self, messages, *, system=None, temperature=0.1, max_tokens=1024) -> str:
        return self._answer(messages)

    async def stream(
        self, messages, *, system=None, temperature=0.1, max_tokens=1024
    ) -> AsyncIterator[str]:
        for word in self._answer(messages).split(" "):
            yield word + " "
