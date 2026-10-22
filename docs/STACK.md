# Stack tecnológico

## Resumen

| Capa | Tecnología | Alternativas ya soportadas | Notas |
|---|---|---|---|
| Lenguaje backend | Python 3.11+ (probado en 3.14) | — | Tipado, `async` de punta a punta |
| API | FastAPI + Uvicorn, Pydantic v2 | — | SSE para streaming, JSON-RPC para A2A |
| Configuración | pydantic-settings (`UNSA_*`, `.env`) | — | Un único `Settings` |
| LLM | Claude, Gemini, OpenRouter, **agy** (CLI Antigravity) | `fake` para pruebas | `agy` no requiere API key |
| Embeddings | `hashing` (por defecto, offline, pruebas) · **local (sentence-transformers, BGE-M3, recomendado)** · Gemini · compatible OpenAI (OpenRouter, Ollama, vLLM) | — | Cambiar de modelo exige reindexar |
| Vector store | SQLite (FTS5 + vectores float32, RRF) | Qdrant, memoria | Híbrido denso + BM25 |
| Persistencia | SQLite (`unsa_mind.db`, WAL, migraciones) | memoria | Fuentes, documentos, schedule, informes |
| Scraping | httpx (cortés, robots.txt, reintentos) | Scrapling (opcional, anti-bot) | |
| Parsing | BeautifulSoup + markdownify (HTML), pypdf (PDF) | — | Conserva jerarquía de títulos/artículos |
| Programación | APScheduler 3.x (`AsyncIOScheduler`) | — | Intervalo o cron, reprogramable en caliente |
| Interoperabilidad | A2A (Agent2Agent) sobre JSON-RPC 2.0 | — | `message/send`, `message/stream`, `tasks/*` |
| CLI | `argparse` (sin dependencias) | — | `serve`, `ask`, `chat`, `agy`, `ingest`, `schedule`, `sources`, `status` |
| Frontend | SvelteKit 2 + Svelte 5 (runes) + TypeScript 5.9 | — | `adapter-node` |
| Estilos | Tailwind CSS 4 | — | Tema granate/dorado, modo oscuro |
| Markdown seguro | marked + DOMPurify | — | |
| Pruebas | pytest + pytest-asyncio · vitest (web) | — | `httpx.MockTransport`, sin red |
| Contenedores | Docker, docker-compose | perfil `qdrant` opcional | |

## Dependencias Python

Núcleo (`pip install -e .`): `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic`, `pydantic-settings`,
`pyyaml`, `apscheduler<4`, `beautifulsoup4`, `markdownify`, `pypdf`.

Extras opcionales:

| Extra | Instala | Para qué |
|---|---|---|
| `scrapling` | `scrapling[fetchers]` | Sitios con anti-bot / JavaScript |
| `qdrant` | `qdrant-client` | Vector store Qdrant |
| `local-embeddings` | `sentence-transformers` | Embeddings locales (BGE-M3) |
| `dev` | `pytest`, `pytest-asyncio`, `ruff` | Desarrollo |

## Decisiones y por qué

| Decisión | Razón |
|---|---|
| **SQLite como vector store por defecto** | El corpus de la UNSA es pequeño (miles de chunks). Evita operar un servicio extra; Qdrant queda como adaptador intercambiable si crece. |
| **Híbrido denso + BM25 + RRF** | Los términos exactos (siglas, "Art. 14", nombres de oficinas) fallan con solo embeddings. |
| **Score normalizado a [0, 1] y umbral de abstención** | Permite decir "no tengo información" en lugar de alucinar (`UNSA_RETRIEVAL_MIN_SCORE`). |
| **Chunking por artículo / sección** | Los reglamentos tienen unidad semántica natural; se anteponen título y ruta jerárquica como contexto. |
| **Hash por documento + versiones inactivas** | Actualizaciones baratas y auditables: solo se re-embebe lo que cambió. |
| **`agy` por NDJSON `stream-json`, sin herramientas** | Evita permisos peligrosos; el material va como texto y se obtiene `usage` real. Cadena de modelos de respaldo ante 503. |
| **Clean architecture** | Cambiar de proveedor LLM, vector store o scraper no toca casos de uso ni dominio. |
| **Frontend desacoplado de la lógica RAG** | Web, A2A, CLI y futuros bots (Telegram/WhatsApp) reutilizan la misma API. |

## Despliegue recomendado

| Entorno | Configuración |
|---|---|
| Desarrollo | `fake` + `hashing` + SQLite; `pnpm dev` con proxy a `:8000` |
| Piloto | `claude` o `gemini` + embeddings `gemini`/`local` + SQLite; un VPS de 2–4 vCPU / 4–8 GB |
| Producción | Lo anterior + Qdrant (`--profile qdrant`), proxy TLS (Caddy/Traefik), `UNSA_ADMIN_TOKEN` fuerte, `UNSA_CORS_ORIGINS` acotado |

## Pendiente / no incluido

- Reranker (el puerto `RerankerPort` existe, sin adaptador).
- Tabla estructurada para datos volátiles (fechas, costos, vacantes).
- Bots de Telegram y WhatsApp (la API ya los soporta como clientes).
- OCR para PDFs escaneados.
- Observabilidad (Langfuse/Prometheus) y evaluación automatizada con dataset propio.
