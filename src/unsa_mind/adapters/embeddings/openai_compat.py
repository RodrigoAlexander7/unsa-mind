"""Embeddings vía API compatible con OpenAI (OpenAI, OpenRouter, Ollama, vLLM...)."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlparse

import httpx

from ._http import EmbeddingError, batched, check_dimension, l2_normalize, post_json

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "text-embedding-3-small"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


class OpenAICompatEmbedder:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        dimension: int = 1536,
        send_dimensions: bool = False,
        client: httpx.AsyncClient | None = None,
        retries: int = 4,
        backoff_s: float = 1.0,
        timeout_s: float = 60.0,
    ) -> None:
        self._base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        host = urlparse(self._base).hostname or ""
        if not api_key and host not in _LOCAL_HOSTS:
            raise EmbeddingError(
                "Falta la API key del embedder: define UNSA_EMBEDDER_API_KEY "
                "(solo es opcional para servidores locales como Ollama o vLLM)."
            )
        self._key = api_key
        self.model = model or DEFAULT_MODEL
        self.dimension = dimension
        self._send_dimensions = send_dimensions
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._retries = retries
        self._backoff = backoff_s

    async def _embed(self, batch: Sequence[str]) -> list[list[float]]:
        payload: dict = {"model": self.model, "input": list(batch)}
        if self._send_dimensions:
            payload["dimensions"] = self.dimension
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        data = await post_json(
            self._client,
            f"{self._base}/embeddings",
            payload,
            headers=headers,
            retries=self._retries,
            backoff_s=self._backoff,
            what=f"embeddings ({self._base})",
        )
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        vecs = [d["embedding"] for d in items]
        if len(vecs) != len(batch):
            raise EmbeddingError("El servidor devolvió un número inesperado de embeddings.")
        check_dimension(vecs, self.dimension, f"El servidor {self._base}")
        return [l2_normalize(v) for v in vecs]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for batch in batched(list(texts)):
            out.extend(await self._embed(batch))
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]

    async def aclose(self) -> None:
        await self._client.aclose()
