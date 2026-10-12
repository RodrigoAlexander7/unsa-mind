"""Utilidades compartidas por los adaptadores HTTP."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .errors import LLMError, TransientLLMError


def error_from_response(provider: str, resp: httpx.Response, body: str | None = None) -> LLMError:
    text = (body if body is not None else resp.text)[:300]
    msg = f"{provider}: HTTP {resp.status_code} {text}"
    if resp.status_code == 429 or resp.status_code >= 500:
        return TransientLLMError(msg)
    return LLMError(msg)


def wrap_transport(provider: str, exc: httpx.HTTPError) -> LLMError:
    return TransientLLMError(f"{provider}: error de red ({type(exc).__name__}: {exc})")


async def post_json(
    client: httpx.AsyncClient, provider: str, url: str, headers: dict[str, str], payload: Any
) -> dict[str, Any]:
    try:
        resp = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise wrap_transport(provider, exc) from exc
    if resp.status_code >= 400:
        raise error_from_response(provider, resp)
    try:
        return resp.json()
    except ValueError as exc:
        raise LLMError(f"{provider}: respuesta no JSON") from exc


async def post_sse(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    headers: dict[str, str],
    payload: Any,
    params: dict[str, str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Emite el JSON de cada línea `data:` de un stream SSE (ignora `[DONE]`)."""
    try:
        async with client.stream(
            "POST", url, headers=headers, json=payload, params=params
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")
                raise error_from_response(provider, resp, body)
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    yield json.loads(data)
                except ValueError as exc:
                    raise LLMError(f"{provider}: evento SSE inválido") from exc
    except httpx.HTTPError as exc:
        raise wrap_transport(provider, exc) from exc
