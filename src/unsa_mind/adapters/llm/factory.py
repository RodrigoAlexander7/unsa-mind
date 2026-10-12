"""Construcción del LLM según la configuración."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from unsa_mind.application.ports import LLMPort
from unsa_mind.config.settings import Settings

from .agy import AgyLLM
from .claude import ClaudeLLM
from .errors import LLMError
from .fallback import FallbackLLM
from .gemini import GeminiLLM
from .openrouter import OpenRouterLLM


def build_llm(settings: Settings, *, client: httpx.AsyncClient | None = None) -> LLMPort:
    provider = settings.llm_provider
    if provider == "fake":
        from unsa_mind.adapters.memory import FakeLLM

        return FakeLLM()

    timeout = settings.llm_timeout_s
    make: Callable[[str | None], LLMPort]
    if provider == "agy":

        def make(model: str | None) -> LLMPort:
            return AgyLLM(model, agy_bin=settings.agy_bin, timeout_s=timeout)

    else:
        table = {
            "claude": (settings.anthropic_api_key, "UNSA_ANTHROPIC_API_KEY", ClaudeLLM),
            "gemini": (settings.gemini_api_key, "UNSA_GEMINI_API_KEY", GeminiLLM),
            "openrouter": (settings.openrouter_api_key, "UNSA_OPENROUTER_API_KEY", OpenRouterLLM),
        }
        if provider not in table:
            raise LLMError(f"proveedor LLM desconocido: {provider}")
        key, env, cls = table[provider]
        if not key:
            raise LLMError(f"{provider}: falta la API key ({env})")

        def make(model: str | None) -> LLMPort:
            return cls(key, model, timeout_s=timeout, client=client)

    models = [settings.llm_model, *settings.llm_fallback_models]
    candidates = [make(m) for m in dict.fromkeys(models)]  # sin duplicados, conserva orden
    return candidates[0] if len(candidates) == 1 else FallbackLLM(candidates)
