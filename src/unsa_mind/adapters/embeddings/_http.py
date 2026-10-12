"""Utilidades comunes de los embedders HTTP: lotes, reintentos con backoff y normalización."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterator, Sequence
from typing import Any

import httpx

MAX_BATCH = 100
_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class EmbeddingError(RuntimeError):
    """Fallo al obtener embeddings (mensaje pensado para mostrarse al operador)."""


def batched(items: Sequence[str], size: int = MAX_BATCH) -> Iterator[Sequence[str]]:
    size = max(1, min(size, MAX_BATCH))
    for i in range(0, len(items), size):
        yield items[i : i + size]


def l2_normalize(v: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    retries: int = 4,
    backoff_s: float = 1.0,
    what: str = "embeddings",
) -> dict[str, Any]:
    last: str = ""
    for attempt in range(retries + 1):
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.TransportError as exc:
            last = f"error de red: {exc!r}"
        else:
            if resp.status_code < 300:
                return resp.json()
            last = f"HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code not in _RETRY_STATUS:
                raise EmbeddingError(f"Fallo en {what}: {last}")
        if attempt < retries:
            await asyncio.sleep(backoff_s * (2**attempt))
    raise EmbeddingError(f"Fallo en {what} tras {retries + 1} intentos: {last}")


def check_dimension(vectors: Sequence[Sequence[float]], expected: int, what: str) -> None:
    for v in vectors:
        if len(v) != expected:
            raise EmbeddingError(
                f"{what} devolvió vectores de dimensión {len(v)} pero se configuró "
                f"embedder_dimension={expected}. Ajusta UNSA_EMBEDDER_DIMENSION "
                "(y reindexa si ya había datos)."
            )
