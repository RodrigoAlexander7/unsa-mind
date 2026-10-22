# API, A2A y CLI

## REST

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado, LLM, chunks indexados, próxima actualización |
| POST | `/api/chat` | SSE: eventos `token`, `final`, `error` |
| POST | `/api/chat/sync` | Respuesta completa en JSON |
| POST | `/api/feedback` | `{message_id?, value: "up"\|"down", comment?}` |

Cuerpo de chat: `{ "message": "...", "history": [{"role": "user", "content": "..."}], "filters": {} }`

Evento `final`:

```json
{"answer": "...", "citations": [{"title": "", "section": "", "url": "", "updated_at": ""}],
 "abstained": false, "intent": "tramites", "data_as_of": "2026-10-12T00:00:00+00:00"}
```

### Administración (`Authorization: Bearer <UNSA_ADMIN_TOKEN>`)

| Método | Ruta | Descripción |
|---|---|---|
| GET/PUT | `/api/admin/schedule` | `{enabled, interval_minutes, cron}`; el PUT se aplica en caliente |
| GET/POST | `/api/admin/sources` | Listar / crear fuentes |
| GET/PUT/DELETE | `/api/admin/sources/{id}` | Gestionar una fuente |
| POST | `/api/admin/update` | `{force?, only?}`; `?wait=true` espera el informe |
| GET | `/api/admin/reports?limit=` | Informes de ejecuciones |
| GET | `/api/admin/stats` | Chunks, documentos y fuentes |
| GET | `/api/admin/documents?source_id=&active_only=true&limit=50&offset=0` | **Solo lectura.** Documentos indexados, más recientes primero: `{total, limit, offset, items[]}` |
| GET | `/api/admin/documents/{doc_id}/chunks` | **Solo lectura.** Texto indexado del documento, por chunks y en orden (`position`, `section`, `text`, `context`, `authority`, `metadata`, `active`) |

Ver qué se guardó de una fuente (el `doc_id` sale del listado anterior):

```bash
curl -s "localhost:8000/api/admin/documents?source_id=admision-portal&limit=5" \
  -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/api/admin/documents/<doc_id>/chunks" -H "Authorization: Bearer $TOKEN"
```

Los documentos reemplazados por una versión nueva siguen existiendo como inactivos:
`active_only=false` los incluye. Si `UNSA_ADMIN_TOKEN` no está definido, `/api/admin` queda abierto
(solo desarrollo) y no hace falta la cabecera.

Ejemplo, actualizar cada día a las 03:00:

```bash
curl -X PUT localhost:8000/api/admin/schedule -H "Authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d '{"enabled": true, "interval_minutes": 1440, "cron": "0 3 * * *"}'
```

## A2A (Agent2Agent)

- **Agent Card:** `GET /.well-known/agent-card.json` (alias `/.well-known/agent.json`).
  Skills: admisión, posgrado, convenios y trámites.
- **JSON-RPC 2.0:** `POST /a2a`.

| Método | Comportamiento |
|---|---|
| `message/send` | Devuelve un `Message` del agente (con citas en `metadata`); un `Task` completado si se envía `taskId` |
| `message/stream` | SSE de eventos JSON-RPC: `working`, `artifact-update`, `completed` |
| `tasks/get` | Consulta una tarea (`-32001` si no existe) |
| `tasks/cancel` | Cancela una tarea (`-32002` si ya terminó) |

El `contextId` mantiene el historial de la conversación (en memoria, acotado).

```bash
curl -X POST localhost:8000/a2a -H "content-type: application/json" -d '{
  "jsonrpc":"2.0","id":1,"method":"message/send",
  "params":{"message":{"role":"user","messageId":"m1",
    "parts":[{"kind":"text","text":"¿Cómo solicito la reserva de matrícula?"}]}}}'
```

## CLI

Tras `pip install -e .` el comando es `unsa-mind`; también sirve `python -m unsa_mind`. Con el
Makefile hay atajos (ver [OPERACION.md §1](OPERACION.md#1-puesta-en-marcha)).

### Opciones globales (valen para cualquier comando)

| Opción | Efecto |
|---|---|
| `--llm {fake,claude,gemini,openrouter,agy}` | Proveedor de LLM; pisa `UNSA_LLM_PROVIDER` |
| `--model NOMBRE` | Modelo del proveedor; pisa `UNSA_LLM_MODEL` |

### Comandos

| Comando | Qué hace | Ejemplo |
|---|---|---|
| `serve [--host H] [--port P]` | Levanta API REST + A2A + scheduler embebido (por defecto `UNSA_HOST`/`UNSA_PORT`) | `unsa-mind serve --port 8000` |
| `ask "pregunta"` | Una consulta; imprime la respuesta, las fuentes con fecha y la vigencia | `unsa-mind ask "¿Cómo reservo matrícula?" --llm agy` |
| `chat` | REPL con historial y streaming. Dentro: `/fuentes` lista fuentes, `/salir` termina | `unsa-mind chat` |
| `agy ["pregunta"]` | Igual que `ask`/`chat` pero fuerza el proveedor `agy`; sin pregunta abre el chat | `unsa-mind agy "¿Requisitos de admisión?"` |
| `ingest [--source ID]... [--force]` | Ciclo de actualización. `--source` (repetible) limita a esas fuentes y las ejecuta aunque no les toque; `--force` ignora los intervalos propios | `unsa-mind ingest --source documentos-locales` |
| `sources list` | Lista las fuentes (`on`/`off`, autoridad, URL) | `unsa-mind sources list` |
| `sources add ID URL [opciones]` | Añade una fuente. Opciones: `--name`, `--kind {html,pdf}`, `--authority {high,medium,low}`, `--follow-links`, `--link-pattern REGEX`, `--max-pages N`, `--interval-minutes N` | `unsa-mind sources add reg https://x.pe/reg.pdf --kind pdf --authority high` |
| `sources enable\|disable\|remove ID` | Activa, desactiva o elimina una fuente | `unsa-mind sources disable noticias` |
| `schedule show` | Muestra el schedule global y el próximo disparo | `unsa-mind schedule show` |
| `schedule set [--interval-minutes N] [--cron "..."] [--enable\|--disable]` | Cambia el schedule global (el cron tiene prioridad; fijar solo un intervalo anula el cron previo) | `unsa-mind schedule set --cron "0 3 * * *"` |
| `status` | Resumen: LLM, chunks, documentos, fuentes, schedule y último ciclo | `unsa-mind status` |

Códigos de salida: `0` correcto, `1` error de ejecución (o ciclo con errores), `2` uso incorrecto.

Notas:
- `sources add` no admite `metadata`; defínala en `config/sources.yaml` o por la API.
- `schedule set` solo persiste. Con el servidor en marcha, aplique el cambio en caliente con
  `PUT /api/admin/schedule` o desde `/admin`.
- Fuentes locales: una fuente cuya URL sea una ruta (p. ej. `data/raw`) o `file://` dentro de
  `UNSA_RAW_DIR` se lee del disco. Ver [OPERACION.md §4](OPERACION.md#4-gestionar-fuentes).

### Atajos del Makefile

| Comando | Equivale a |
|---|---|
| `make install` | venv + `pip install -e ".[dev]"` + `pnpm install` + crea `.env` (embeddings `hashing`) |
| `make install-ocr` | añade MarkItDown (OCR de PDF escaneados + DOCX/PPTX/XLSX); luego `UNSA_OCR_PROVIDER=agy` |
| `make install-bge` | añade BGE-M3 (`.[local-embeddings]`, arrastra PyTorch); luego configurar `local` y reindexar |
| `make backend` | `unsa-mind serve` con `UNSA_LLM_PROVIDER=$(LLM)` (por defecto `agy`) |
| `make frontend` | `pnpm dev` en `web/` |
| `make dev` | backend y frontend a la vez |
| `make ingest` / `make chat` / `make status` | los comandos homónimos de la CLI |
| `make test` / `make check-web` / `make build-web` | pruebas del backend / tipos y tests del frontend / build |
| `make docker-up` / `make docker-down` | Docker Compose |

Variables: `LLM`, `HOST`, `PORT`, `WEB_PORT`; p. ej. `make backend LLM=gemini PORT=9000`.

## Variables de entorno principales

Ver [`.env.example`](../.env.example). Las más relevantes: `UNSA_LLM_PROVIDER`, `UNSA_LLM_MODEL`,
`UNSA_LLM_FALLBACK_MODELS`, `UNSA_ANTHROPIC_API_KEY` / `UNSA_GEMINI_API_KEY` / `UNSA_OPENROUTER_API_KEY`,
`UNSA_EMBEDDER_PROVIDER`, `UNSA_VECTOR_STORE`, `UNSA_SCHEDULE_INTERVAL_MINUTES`, `UNSA_SCHEDULE_CRON`,
`UNSA_RETRIEVAL_MIN_SCORE`, `UNSA_ADMIN_TOKEN`, `UNSA_PUBLIC_URL`.
