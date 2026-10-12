"""Adaptador Anthropic Messages API (httpx)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from unsa_mind.application.ports import ChatMessage

from ._http import post_json, post_sse
from .errors import LLMError

URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"


class ClaudeLLM:
    name = "claude"

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
            raise LLMError("claude: falta UNSA_ANTHROPIC_API_KEY")
        self.model = model or DEFAULT_MODEL
        self._url = url
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        system: str | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if system:
            payload["system"] = system
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
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise LLMError("claude: respuesta vacía")
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
            if event.get("type") == "error":
                raise LLMError(f"claude: {event.get('error')}")
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield delta["text"]
