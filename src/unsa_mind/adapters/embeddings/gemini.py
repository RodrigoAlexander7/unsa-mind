"""Embeddings de Gemini (generativelanguage.googleapis.com: embedContent / batchEmbedContents)."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from ._http import EmbeddingError, batched, check_dimension, l2_normalize, post_json

DEFAULT_MODEL = "gemini-embedding-001"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str | None,
        *,
        model: str | None = None,
        dimension: int = 768,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
        retries: int = 4,
        backoff_s: float = 1.0,
        timeout_s: float = 60.0,
    ) -> None:
        if not api_key:
            raise EmbeddingError(
                "Falta la API key de Gemini para los embeddings: define UNSA_GEMINI_API_KEY."
            )
        self._key = api_key
        self.model = (model or DEFAULT_MODEL).removeprefix("models/")
        self.dimension = dimension
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._base = base_url.rstrip("/")
        self._retries = retries
        self._backoff = backoff_s

    def _request(self, text: str, task_type: str) -> dict:
        return {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": self.dimension,
        }

    async def _post(self, path: str, payload: dict) -> dict:
        return await post_json(
            self._client,
            f"{self._base}/models/{self.model}:{path}",
            payload,
            headers={"x-goog-api-key": self._key, "Content-Type": "application/json"},
            retries=self._retries,
            backoff_s=self._backoff,
            what="Gemini embeddings",
        )

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for batch in batched(list(texts)):
            data = await self._post(
                "batchEmbedContents",
                {"requests": [self._request(t, "RETRIEVAL_DOCUMENT") for t in batch]},
            )
            vecs = [e["values"] for e in data.get("embeddings", [])]
            if len(vecs) != len(batch):
                raise EmbeddingError("Gemini devolvió un número inesperado de embeddings.")
            out.extend(vecs)
        check_dimension(out, self.dimension, "Gemini")
        # Con outputDimensionality < 3072 los vectores no vienen normalizados.
        return [l2_normalize(v) for v in out]

    async def embed_query(self, text: str) -> list[float]:
        data = await self._post("embedContent", self._request(text, "RETRIEVAL_QUERY"))
        vec = data["embedding"]["values"]
        check_dimension([vec], self.dimension, "Gemini")
        return l2_normalize(vec)

    async def aclose(self) -> None:
        await self._client.aclose()
