# unsa-mind

Asistente virtual institucional de la Universidad Nacional de San Agustín (UNSA): RAG híbrido
sobre admisión, posgrado, convenios y trámites, con actualización por web scraping programable,
API REST + SvelteKit, interfaz **A2A** (agent-to-agent) y CLI.

## Arquitectura (clean architecture / puertos y adaptadores)

```
domain/            entidades y errores (sin dependencias)
application/
  ports/           LLM, Embedder, VectorStore, Fetcher, Parser, Scheduler, Repositorios, Reranker
  services/        chunker estructural, router de intención, prompts
  use_cases/       AskQuestion, IngestSource, RunUpdateCycle
adapters/          llm (claude, gemini, openrouter, agy) · embeddings · vectorstore (sqlite, qdrant)
                   persistence (sqlite) · scraping (httpx, scrapling, html, pdf) · scheduling · memory
interfaces/        api (FastAPI + SSE) · a2a (JSON-RPC) · cli
config/            settings (UNSA_*) y raíz de composición (container.py)
web/               SvelteKit (chat, /embed, /admin)
```

La dependencia apunta siempre hacia adentro: `interfaces → application → domain`; los adaptadores
implementan los puertos y solo `config/container.py` los conoce.

## Actualización con scraping

- Catálogo de fuentes: `config/sources.yaml` (semilla) y CRUD en `/api/admin/sources`.
- Frecuencia global **ajustable en caliente**: intervalo en minutos o cron, vía
  `unsa-mind schedule set --cron "0 3 * * *"`, `PUT /api/admin/schedule` o la pestaña *Programación* del admin.
- Cada fuente puede tener su propio `interval_minutes` (p. ej. noticias cada 4 h, reglamentos semanal).
- Detección por hash: solo se re-embeben los documentos que cambiaron; las versiones anteriores
  quedan inactivas (auditoría), no se borran.

## Uso rápido

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
cp .env.example .env
unsa-mind ingest            # rastrear fuentes
unsa-mind chat              # REPL con el LLM configurado
unsa-mind agy               # REPL usando el CLI agy directamente (sin API key)
unsa-mind serve             # API + scheduler en :8000
```

Proveedores LLM: `UNSA_LLM_PROVIDER=claude|gemini|openrouter|agy|fake` (+ la API key correspondiente).

## A2A

Agent Card en `/.well-known/agent-card.json`; JSON-RPC en `POST /a2a` (`message/send`,
`message/stream`, `tasks/get`, `tasks/cancel`).
