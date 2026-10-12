from __future__ import annotations

import httpx

from unsa_mind.adapters.memory import HashingEmbedder
from unsa_mind.application.ports import EmbedderPort
from unsa_mind.config.settings import Settings

from .gemini import GeminiEmbedder
from .local import LocalEmbedder
from .openai_compat import OpenAICompatEmbedder


def build_embedder(settings: Settings, client: httpx.AsyncClient | None = None) -> EmbedderPort:
    provider = settings.embedder_provider
    if provider == "hashing":
        return HashingEmbedder(settings.embedder_dimension)
    if provider == "gemini":
        return GeminiEmbedder(
            settings.gemini_api_key,
            model=settings.embedder_model,
            dimension=settings.embedder_dimension,
            client=client,
        )
    if provider == "openai_compat":
        return OpenAICompatEmbedder(
            base_url=settings.embedder_base_url,
            api_key=settings.embedder_api_key,
            model=settings.embedder_model,
            dimension=settings.embedder_dimension,
            client=client,
        )
    if provider == "local":
        return LocalEmbedder(model=settings.embedder_model, dimension=settings.embedder_dimension)
    raise ValueError(f"Embedder desconocido: {provider!r}")
