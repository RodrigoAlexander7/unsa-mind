"""Cadena de respaldo con reintentos y backoff sobre varios LLMPort."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from unsa_mind.application.ports import ChatMessage, LLMPort

from .errors import LLMError, TransientLLMError


class FallbackLLM:
    """Prueba cada candidato en orden; reintenta con backoff solo los fallos transitorios."""

    def __init__(
        self, candidates: Sequence[LLMPort], *, attempts: int = 2, backoff_s: float = 1.0
    ) -> None:
        if not candidates:
            raise ValueError("FallbackLLM requiere al menos un candidato")
        self._candidates = list(candidates)
        self._attempts = max(1, attempts)
        self._backoff = backoff_s
        self.name = self._candidates[0].name

    async def _sleep(self, attempt: int) -> None:
        if self._backoff > 0:
            await asyncio.sleep(self._backoff * 2**attempt)

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        last: LLMError | None = None
        for llm in self._candidates:
            for attempt in range(self._attempts):
                try:
                    return await llm.complete(
                        messages, system=system, temperature=temperature, max_tokens=max_tokens
                    )
                except TransientLLMError as exc:
                    last = exc
                    if attempt + 1 < self._attempts:
                        await self._sleep(attempt)
                except LLMError as exc:  # permanente: pasa al siguiente candidato
                    last = exc
                    break
        raise last or LLMError("sin candidatos")

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        last: LLMError | None = None
        for llm in self._candidates:
            for attempt in range(self._attempts):
                started = False
                try:
                    async for chunk in llm.stream(
                        messages, system=system, temperature=temperature, max_tokens=max_tokens
                    ):
                        started = True
                        yield chunk
                    return
                except LLMError as exc:
                    if started:  # ya se emitió texto: no se puede reanudar con otro modelo
                        raise
                    last = exc
                    if not isinstance(exc, TransientLLMError):
                        break
                    if attempt + 1 < self._attempts:
                        await self._sleep(attempt)
        raise last or LLMError("sin candidatos")
