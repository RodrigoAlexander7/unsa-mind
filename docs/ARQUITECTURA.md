# Arquitectura

Clean architecture con puertos y adaptadores. La dependencia apunta siempre hacia adentro. El detalle del motor de recuperación y generación está en [RAG.md](RAG.md).

```
interfaces ──► application ──► domain
   (API, A2A, CLI)   (casos de uso, puertos)   (entidades)
        ▲                  ▲
        └──── adapters ────┘   implementan los puertos
              config/container.py  es el único que los conoce
```

## Capas

| Capa | Ruta | Responsabilidad |
|---|---|---|
| Dominio | `src/unsa_mind/domain/` | `Source`, `Chunk`, `Answer`, `Schedule`, `Authority`, `Intent`, errores. Sin dependencias externas |
| Aplicación | `application/` | Puertos (`ports/`), servicios (`chunker`, `intent`, `prompts`) y casos de uso |
| Adaptadores | `adapters/` | `llm`, `embeddings`, `vectorstore`, `persistence`, `scraping`, `scheduling`, `memory` |
| Interfaces | `interfaces/` | `api` (FastAPI), `a2a`, `cli` |
| Composición | `config/` | `settings.py` (`UNSA_*`) y `container.py` (raíz de composición) |
| Web | `web/` | SvelteKit: chat, `/embed`, `/admin` |

## Puertos

| Puerto | Adaptadores |
|---|---|
| `LLMPort` | `ClaudeLLM`, `GeminiLLM`, `OpenRouterLLM`, `AgyLLM`, `FallbackLLM`, `FakeLLM` |
| `EmbedderPort` | `HashingEmbedder`, `GeminiEmbedder`, `OpenAICompatEmbedder`, `LocalEmbedder` |
| `VectorStorePort` | `SqliteVectorStore`, `QdrantVectorStore`, `InMemoryVectorStore` |
| `FetcherPort` | `HttpxFetcher`, `ScraplingFetcher` |
| `ParserPort` | `HtmlParser`, `PdfParser` |
| `SourceRepositoryPort`, `DocumentRepositoryPort`, `SettingsRepositoryPort` | SQLite, memoria |
| `SchedulerPort` | `ApSchedulerAdapter` |
| `RerankerPort` | (sin adaptador todavía) |

Para añadir un proveedor: implementar el puerto en `adapters/<tipo>/`, registrarlo en su `factory.py`
y ampliar el `Literal` correspondiente de `Settings`. No se toca nada más.

## Flujo de consulta (`AskQuestion`)

1. **Intención** (heurística): admisión, posgrado, convenios, trámites, general, fuera de alcance.
   Fuera de alcance responde con un mensaje fijo.
2. **Recuperación híbrida**: embedding de la consulta, búsqueda densa + BM25 fusionadas con RRF,
   solo chunks activos, filtros opcionales por metadata.
3. **Autoridad**: el score se multiplica por el peso de la fuente (reglamento > noticia).
4. **Rerank** opcional y recorte a `top_n`.
5. **Abstención** (CRAG simplificado): si el mejor score no supera `retrieval_min_score`,
   responde con la derivación a la oficina correspondiente, sin invocar al LLM.
6. **Generación**: prompt de secretaría académica, documentos numerados `[n]`, últimos 6 turnos de historial.
7. **Citas**: se devuelven los documentos referenciados `[n]` (o los 3 mejores) y la fecha de vigencia.

## Flujo de actualización (`RunUpdateCycle` → `IngestSource`)

```
Scheduler/API/CLI ─► RunUpdateCycle ─► IngestSource (por fuente, concurrencia 3)
   fetch (BFS, max_pages, link_pattern) ─► parse a Markdown ─► hash
   ├─ hash igual   → sin cambios
   └─ hash nuevo   → chunking estructural → embeddings → upsert
                     versión anterior → inactiva (no se borra)
```

- **Frecuencia global** (`Schedule`): intervalo en minutos o cron de 5 campos; el cron tiene prioridad.
  Persistida y reprogramable en caliente.
- **Frecuencia por fuente** (`interval_minutes`): la fuente solo corre si ya transcurrió ese intervalo.
  Sin valor propio, corre en cada disparo global. `force` o `only=[ids]` lo ignoran.
- Un error en una página no aborta la fuente; queda en el informe (`SourceReport.errors`).
- Un candado evita ciclos solapados.

## Chunking

Parte por títulos Markdown y por `Artículo N`; si una sección supera ~2400 caracteres se subdivide por
párrafos con ~10 % de traslape; fragmentos menores a 200 caracteres se fusionan. Cada chunk lleva
`context` (título + ruta jerárquica) que se antepone al embeber, y la metadata de la fuente.

## Seguridad

- `Authorization: Bearer <UNSA_ADMIN_TOKEN>` en `/api/admin/*` (abierto solo si no hay token: desarrollo).
- Límite de tasa por IP en el chat; CORS acotado por configuración.
- Prompt con regla explícita de ignorar instrucciones dentro de la consulta o los documentos.
- `agy` se invoca sin `--dangerously-skip-permissions` y sin herramientas.
- El feedback no almacena datos personales.
