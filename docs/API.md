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

```bash
unsa-mind serve                              # API + A2A + scheduler embebido
unsa-mind ask "pregunta" [--llm claude]      # una consulta con citas
unsa-mind chat                               # REPL con historial y streaming
unsa-mind agy ["pregunta"]                   # usa el CLI agy directamente (sin API key)
unsa-mind ingest [--source ID] [--force]     # ciclo de actualización
unsa-mind sources list|add|remove|enable|disable
unsa-mind schedule show
unsa-mind schedule set --interval-minutes 360
unsa-mind schedule set --cron "0 3 * * *"
unsa-mind schedule set --disable
unsa-mind status
```

Opciones globales: `--llm {fake,claude,gemini,openrouter,agy}` y `--model`.

## Variables de entorno principales

Ver [`.env.example`](../.env.example). Las más relevantes: `UNSA_LLM_PROVIDER`, `UNSA_LLM_MODEL`,
`UNSA_LLM_FALLBACK_MODELS`, `UNSA_ANTHROPIC_API_KEY` / `UNSA_GEMINI_API_KEY` / `UNSA_OPENROUTER_API_KEY`,
`UNSA_EMBEDDER_PROVIDER`, `UNSA_VECTOR_STORE`, `UNSA_SCHEDULE_INTERVAL_MINUTES`, `UNSA_SCHEDULE_CRON`,
`UNSA_RETRIEVAL_MIN_SCORE`, `UNSA_ADMIN_TOKEN`, `UNSA_PUBLIC_URL`.
