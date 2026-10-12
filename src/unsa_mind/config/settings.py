"""Configuración única (variables de entorno `UNSA_*` o archivo `.env`)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UNSA_", env_file=".env", extra="ignore")

    # --- LLM (puerto LLMPort) ---
    llm_provider: Literal["fake", "claude", "gemini", "openrouter", "agy"] = "fake"
    llm_model: str | None = None  # None => modelo por defecto del proveedor
    llm_fallback_models: list[str] = Field(default_factory=list)  # cadena de respaldo
    llm_timeout_s: float = 60.0
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    agy_bin: str = "agy"

    # --- Embeddings (puerto EmbedderPort) ---
    embedder_provider: Literal["hashing", "gemini", "openai_compat", "local"] = "hashing"
    embedder_model: str | None = None
    embedder_dimension: int = 512
    embedder_base_url: str | None = None  # openai_compat (OpenRouter, vLLM, Ollama...)
    embedder_api_key: str | None = None

    # --- Almacenamiento ---
    vector_store: Literal["memory", "sqlite", "qdrant"] = "sqlite"
    repository: Literal["memory", "sqlite"] = "sqlite"
    data_dir: Path = Path("data")
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "unsa_chunks"

    # --- Scraping ---
    fetcher: Literal["httpx", "scrapling"] = "httpx"
    user_agent: str = "UnsaMindBot/0.1 (+asistente institucional; contacto: configurar)"
    request_delay_s: float = 1.0
    respect_robots: bool = True
    sources_file: Path = Path("config/sources.yaml")

    # --- Actualización programada (modificable en caliente vía API/CLI) ---
    schedule_enabled: bool = True
    schedule_interval_minutes: int = 1440
    schedule_cron: str | None = None  # p. ej. "0 3 * * *"; tiene prioridad sobre el intervalo
    run_scheduler: bool = True  # en la API: levanta el scheduler embebido

    # --- Recuperación ---
    retrieval_candidates: int = 20
    retrieval_top_n: int = 6
    retrieval_min_score: float = 0.15

    # --- Interfaces ---
    host: str = "0.0.0.0"
    port: int = 8000
    admin_token: str | None = None  # si es None, /admin queda abierto (solo desarrollo)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    public_url: str = "http://localhost:8000"  # URL base que anuncia el Agent Card A2A


def get_settings() -> Settings:
    return Settings()
