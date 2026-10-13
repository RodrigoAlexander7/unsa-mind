# unsa-mind

Asistente virtual institucional de la **Universidad Nacional de San Agustín (UNSA)**. Responde con
precisión de secretaría académica sobre admisión, posgrado, convenios y trámites, **citando la fuente
y la fecha de vigencia**, y se abstiene —derivando a la oficina correcta— cuando no tiene información.

## Qué incluye

| Capacidad | Descripción |
|---|---|
| RAG híbrido | Chunking por artículo, búsqueda densa + BM25 con RRF, prioridad por autoridad, abstención por umbral |
| Actualización por scraping | Fuentes configurables, detección de cambios por hash, versionado, frecuencia ajustable en caliente (intervalo o cron) |
| LLM intercambiable | Claude, Gemini, OpenRouter o el CLI `agy` (sin API key) |
| Interfaces | API REST con streaming SSE, **A2A** (agent-to-agent), CLI y web SvelteKit (chat, `/embed`, `/admin`) |
| Arquitectura | Clean architecture con puertos y adaptadores |

## Inicio rápido

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Linux/macOS: .venv/bin/pip
cp .env.example .env
unsa-mind ingest                 # rastrea config/sources.yaml
unsa-mind agy "¿Cómo solicito la reserva de matrícula?"   # usa el CLI agy, sin API key
unsa-mind serve                  # API + A2A + scheduler en :8000
cd web && pnpm install && pnpm dev   # interfaz en :5173
```

> Con `UNSA_LLM_PROVIDER=fake` y `UNSA_EMBEDDER_PROVIDER=hashing` (valores por defecto) todo corre
> offline, útil para probar. Para calidad real configure un LLM y embeddings reales
> ([guía](docs/OPERACION.md#2-elegir-proveedor-de-llm)).

## Cómo funciona (resumen)

```
Fuentes UNSA ─► fetch ─► Markdown con jerarquía ─► ¿hash cambió? ─► chunks + contexto ─► embeddings ─► índice híbrido
Pregunta ─► intención ─► búsqueda híbrida (denso+BM25, RRF) ─► peso por autoridad ─► ¿score ≥ umbral?
                                                        ├─ no ─► abstención + oficina a consultar
                                                        └─ sí ─► LLM con prompt de secretaría ─► respuesta + citas + vigencia
```

## Documentación

| Documento | Contenido |
|---|---|
| [docs/RAG.md](docs/RAG.md) | **El cerebro**: técnicas de RAG, fórmulas, decisiones, límites y hoja de ruta |
| [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) | Capas, puertos y adaptadores, flujos, seguridad |
| [docs/STACK.md](docs/STACK.md) | Tecnologías, dependencias, decisiones y despliegue |
| [docs/API.md](docs/API.md) | REST, A2A (JSON-RPC) y comandos de la CLI |
| [docs/OPERACION.md](docs/OPERACION.md) | Puesta en marcha, fuentes, programación, calibración, solución de problemas |

## Estructura

```
src/unsa_mind/
  domain/        entidades y errores
  application/   puertos, servicios (chunker, intención, prompts) y casos de uso
  adapters/      llm · embeddings · vectorstore · persistence · scraping · scheduling · memory
  interfaces/    api (FastAPI) · a2a · cli
  config/        settings (UNSA_*) y raíz de composición
web/             SvelteKit
config/          sources.yaml (catálogo semilla de fuentes)
docs/            documentación
tests/           pytest, sin red
```

## Estado y advertencias

- Las URLs de `config/sources.yaml` son **provisionales**: confirme las reales y la autorización de
  la UNSA para rastrearlas (robots.txt y términos de uso).
- Fechas, costos y vacantes aún se resuelven por texto; la tabla estructurada es la mejora prioritaria
  ([RAG.md §7](docs/RAG.md#7-límites-conocidos-honestidad-técnica)).
- Proveedores probados con transporte simulado; `agy` probado en real. Claude/Gemini/OpenRouter con
  API key real, Qdrant y Scrapling real están sin validar.
- Asistente informativo: para trámites oficiales, consulte en Secretaría.
