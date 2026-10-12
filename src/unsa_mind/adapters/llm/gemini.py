"""Adaptador Google Generative Language API v1beta (httpx)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from unsa_mind.application.ports import ChatMessage

from ._http import post_json, post_sse
from .errors import LLMError

BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash"


def _text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for cand in data.get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []):
            parts.append(part.get("text", ""))
    return "".join(parts)


class GeminiLLM:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        *,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE,
    ) -> None:
        if not api_key:
            raise LLMError("gemini: falta UNSA_GEMINI_API_KEY")
        self.model = model or DEFAULT_MODEL
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._headers = {"x-goog-api-key": api_key, "content-type": "application/json"}

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                }
                for m in messages
            ],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
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
            f"{self._base}/models/{self.model}:generateContent",
            self._headers,
            self._payload(messages, system, temperature, max_tokens),
        )
        text = _text(data)
        if not text:
            raise LLMError("gemini: respuesta vacía")
        return text

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        url = f"{self._base}/models/{self.model}:streamGenerateContent"
        payload = self._payload(messages, system, temperature, max_tokens)
        async for event in post_sse(
            self._client, self.name, url, self._headers, payload, params={"alt": "sse"}
        ):
            if chunk := _text(event):
                yield chunk
