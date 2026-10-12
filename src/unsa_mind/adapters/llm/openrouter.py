"""Adaptador OpenRouter (API compatible con OpenAI chat/completions)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from unsa_mind.application.ports import ChatMessage

from ._http import post_json, post_sse
from .errors import LLMError

URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


class OpenRouterLLM:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        *,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
        url: str = URL,
    ) -> None:
        if not api_key:
            raise LLMError("openrouter: falta UNSA_OPENROUTER_API_KEY")
        self.model = model or DEFAULT_MODEL
        self._url = url
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        system: str | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        msgs: list[dict[str, str]] = [{"role": "system", "content": system}] if system else []
        msgs += [{"role": m.role, "content": m.content} for m in messages]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stream:
            payload["stream"] = True
        return payload

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        data = await post_json(
            self._client,
            self.name,
            self._url,
            self._headers,
            self._payload(messages, system, temperature, max_tokens, False),
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"openrouter: respuesta inesperada ({str(data)[:200]})") from exc
        if not text:
            raise LLMError("openrouter: respuesta vacía")
        return text

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, system, temperature, max_tokens, True)
        async for event in post_sse(self._client, self.name, self._url, self._headers, payload):
            if "error" in event:
                raise LLMError(f"openrouter: {event['error']}")
            for choice in event.get("choices", []):
                if text := (choice.get("delta") or {}).get("content"):
                    yield text
