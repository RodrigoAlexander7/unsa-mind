"""Caso de uso: responder una consulta (RAG híbrido + rerank + abstención + citas)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from unsa_mind.application.ports import (
    ChatMessage,
    EmbedderPort,
    LLMPort,
    RerankerPort,
    VectorStorePort,
)
from unsa_mind.application.services import prompts
from unsa_mind.application.services.intent import classify_intent
from unsa_mind.domain.entities import Answer, Citation, Intent, ScoredChunk

_CITE = re.compile(r"\[(\d+)\]")
_MAX_HISTORY = 6


@dataclass(frozen=True)
class AskConfig:
    candidates: int = 20
    top_n: int = 6
    min_score: float = 0.15  # por debajo => abstención (CRAG simplificado)
    temperature: float = 0.1
    max_tokens: int = 1024


@dataclass
class StreamEvent:
    kind: str  # "token" | "final"
    token: str = ""
    answer: Answer | None = None


@dataclass
class _Prepared:
    intent: Intent
    immediate: Answer | None = None
    hits: list[ScoredChunk] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)


class AskQuestion:
    def __init__(
        self,
        *,
        llm: LLMPort,
        embedder: EmbedderPort,
        vector_store: VectorStorePort,
        reranker: RerankerPort | None = None,
        config: AskConfig | None = None,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._store = vector_store
        self._reranker = reranker
        self._cfg = config or AskConfig()

    # ---- API pública -----------------------------------------------------------------
    async def execute(
        self,
        question: str,
        *,
        history: Sequence[ChatMessage] = (),
        filters: dict[str, Any] | None = None,
    ) -> Answer:
        prep = await self._prepare(question, history, filters)
        if prep.immediate:
            return prep.immediate
        text = await self._llm.complete(
            prep.messages,
            system=prompts.SYSTEM_PROMPT,
            temperature=self._cfg.temperature,
            max_tokens=self._cfg.max_tokens,
        )
        return self._finalize(text, prep)

    async def stream(
        self,
        question: str,
        *,
        history: Sequence[ChatMessage] = (),
        filters: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        prep = await self._prepare(question, history, filters)
        if prep.immediate:
            yield StreamEvent("token", token=prep.immediate.text)
            yield StreamEvent("final", answer=prep.immediate)
            return
        parts: list[str] = []
        async for token in self._llm.stream(
            prep.messages,
            system=prompts.SYSTEM_PROMPT,
            temperature=self._cfg.temperature,
            max_tokens=self._cfg.max_tokens,
        ):
            parts.append(token)
            yield StreamEvent("token", token=token)
        yield StreamEvent("final", answer=self._finalize("".join(parts), prep))

    # ---- internos --------------------------------------------------------------------
    async def _prepare(
        self, question: str, history: Sequence[ChatMessage], filters: dict[str, Any] | None
    ) -> _Prepared:
        intent = classify_intent(question)
        if intent is Intent.OUT_OF_SCOPE:
            return _Prepared(intent, Answer(prompts.OUT_OF_SCOPE, abstained=True, intent=intent))

        vector = await self._embedder.embed_query(question)
        hits = await self._store.search(
            query_text=question, query_vector=vector, k=self._cfg.candidates, filters=filters
        )
        hits = [ScoredChunk(h.chunk, h.score * h.chunk.authority.boost) for h in hits]
        hits.sort(key=lambda h: h.score, reverse=True)
        if self._reranker and hits:
            hits = await self._reranker.rerank(question, hits, self._cfg.top_n)
        hits = hits[: self._cfg.top_n]

        if not hits or hits[0].score < self._cfg.min_score:
            office = prompts.OFFICES.get(intent.value, prompts.DEFAULT_OFFICE)
            text = prompts.ABSTENTION_TEMPLATE.format(office=office)
            return _Prepared(intent, Answer(text, abstained=True, intent=intent))

        docs = "\n\n".join(
            f"[{i}] {h.chunk.title} — {h.chunk.section} "
            f"(actualizado: {h.chunk.updated_at:%d/%m/%Y})\n{h.chunk.text}"
            for i, h in enumerate(hits, 1)
        )
        messages = [*history[-_MAX_HISTORY:], ChatMessage("user", prompts.build_user_prompt(question, docs))]
        return _Prepared(intent, None, hits, messages)

    def _finalize(self, text: str, prep: _Prepared) -> Answer:
        text = text.strip()
        cited = sorted({int(n) for n in _CITE.findall(text) if 1 <= int(n) <= len(prep.hits)})
        used = [prep.hits[n - 1] for n in cited] or prep.hits[:3]
        citations = [
            Citation(h.chunk.title, h.chunk.section, h.chunk.url, h.chunk.updated_at) for h in used
        ]
        return Answer(
            text=text,
            citations=citations,
            abstained=False,
            intent=prep.intent,
            data_as_of=max(h.chunk.updated_at for h in used),
        )
