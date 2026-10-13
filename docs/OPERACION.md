# Guía de operación

## 1. Puesta en marcha

### Requisitos
Python 3.11+, Node 20+ y pnpm (solo para el frontend), Docker (opcional).

### Backend

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # Linux/macOS: .venv/bin/pip
cp .env.example .env                        # editar proveedor y claves
unsa-mind ingest                            # rastrea las fuentes de config/sources.yaml
unsa-mind ask "¿Cómo solicito la reserva de matrícula?"
unsa-mind serve                             # API + A2A + scheduler en :8000
```

### Frontend

```bash
cd web
pnpm install
pnpm dev                                    # http://localhost:5173 (proxy a :8000)
```

### Docker

```bash
docker compose up --build                   # api :8000, web :3000
docker compose --profile qdrant up          # añade Qdrant
```

## 2. Elegir proveedor de LLM

| Proveedor | Configuración | Cuándo usarlo |
|---|---|---|
| `agy` | `UNSA_LLM_PROVIDER=agy` (sin API key; requiere `agy` en el PATH) | Desarrollo y uso personal. Es más lento (~10 s por turno) |
| `claude` | `UNSA_LLM_PROVIDER=claude` + `UNSA_ANTHROPIC_API_KEY` | Producción, mejor calidad |
| `gemini` | `UNSA_LLM_PROVIDER=gemini` + `UNSA_GEMINI_API_KEY` | Producción, bajo costo |
| `openrouter` | `UNSA_LLM_PROVIDER=openrouter` + `UNSA_OPENROUTER_API_KEY` | Probar muchos modelos |
| `fake` | por defecto | Pruebas sin red |

Respaldo ante fallos: `UNSA_LLM_FALLBACK_MODELS='["modelo-b","modelo-c"]'` (cadena con reintentos y
backoff). Con `agy`, la lista de modelos disponibles sale de `agy models`.

## 3. Elegir embeddings (afecta la calidad de recuperación)

| Proveedor | Configuración | Nota |
|---|---|---|
| `hashing` | por defecto | Offline, **léxico**; solo para pruebas |
| `gemini` | `UNSA_EMBEDDER_PROVIDER=gemini` + `UNSA_GEMINI_API_KEY` | Buena calidad multilingüe |
| `openai_compat` | `UNSA_EMBEDDER_BASE_URL`, `UNSA_EMBEDDER_API_KEY`, `UNSA_EMBEDDER_MODEL` | OpenRouter, OpenAI, Ollama, vLLM |
| `local` | `pip install -e ".[local-embeddings]"` | BGE-M3 sin salir a internet |

**Cambiar de modelo o dimensión exige reindexar.** El índice guarda `dimension` y `embedder_id`; si no
coinciden falla con un mensaje claro. Para reindexar: borrar `data/vectors.db` y `data/unsa_mind.db`
(o la carpeta `data/`) y ejecutar `unsa-mind ingest`.

## 4. Gestionar fuentes

Las fuentes se siembran desde `config/sources.yaml` al arrancar (sin pisar las editadas después) y
se administran luego por CLI, API o el panel `/admin`.

```yaml
sources:
  - id: reglamento-matricula
    name: Reglamento de Matrícula
    url: https://ejemplo.unsa.edu.pe/reglamento.pdf
    kind: pdf                # html | pdf
    authority: high          # high | medium | low
    interval_minutes: 10080  # opcional: semanal; sin valor, corre en cada disparo global
    follow_links: false      # true para rastrear enlaces internos
    link_pattern: "/admision/"   # regex de enlaces a seguir
    max_pages: 20
    metadata: {tema: tramites, nivel: pregrado, facultad: ingenieria}
```

```bash
unsa-mind sources list
unsa-mind sources add reglamento https://ejemplo.unsa.edu.pe/reg.pdf --kind pdf --authority high --interval-minutes 10080
unsa-mind sources disable reglamento            # también: enable, remove
unsa-mind ingest --source reglamento-matricula   # ejecutar una fuente ahora
unsa-mind ingest --force                         # ignora intervalos propios
```

**Buenas prácticas:** una fuente por tipo de documento; `authority: high` solo para texto normativo;
poner `metadata` útil (`facultad`, `nivel`, `tema`) porque habilita filtros; mantener
`UNSA_RESPECT_ROBOTS=true` y un `UNSA_REQUEST_DELAY_S` ≥ 1.

## 5. Programar la actualización

| Objetivo | Comando |
|---|---|
| Cada 6 horas | `unsa-mind schedule set --interval-minutes 360` |
| Todos los días a las 03:00 | `unsa-mind schedule set --cron "0 3 * * *"` |
| Pausar | `unsa-mind schedule set --disable` |
| Ver estado y próximo disparo | `unsa-mind schedule show` |

Con el servidor en marcha, aplique el cambio **en caliente** con `PUT /api/admin/schedule` o desde
el panel `/admin` → *Programación* (la CLI solo persiste; `sources add` no admite `metadata`, defínala en el YAML o por la API). Combine el cron global con
`interval_minutes` por fuente: p. ej. cron cada hora, noticias con 240 min y reglamentos con 10080.

## 6. Verificar que funciona

```bash
unsa-mind status                       # chunks, documentos, última ejecución
curl localhost:8000/api/health
pytest -q                              # suite completa (sin red)
```

Señales de salud en `/api/admin/reports`: `errors` vacío, `unchanged` alto entre ejecuciones
(la detección por hash funciona) y `chunks_indexed` > 0 solo cuando hubo cambios reales.

## 7. Evaluación y calibración

Aún no hay un arnés de evaluación automático. Procedimiento manual recomendado:

1. Crear un archivo con 100–200 preguntas reales (admisión, posgrado, convenios, trámites), cada una
   con la respuesta esperada o la marca **"sin respuesta"** (15–20 % del total).
2. Ejecutar `unsa-mind ask "…"` o `POST /api/chat/sync` por cada una y revisar citas y abstención.
3. Medir: **abstención correcta** en las "sin respuesta", **exactitud de datos críticos** (fechas,
   costos), **citas verificables** y recuperación (¿el documento correcto está entre los citados?).
4. Ajustar `UNSA_RETRIEVAL_MIN_SCORE` (más alto = más abstenciones, menos riesgo), `UNSA_RETRIEVAL_TOP_N`
   y las fuentes faltantes. Repetir tras cada cambio de embeddings, chunking o prompt.
5. Complementar con revisión humana periódica de personal de secretaría.

## 8. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Siempre responde "no cuento con información" | Índice vacío o umbral alto | `unsa-mind status`; ejecutar `ingest`; bajar `UNSA_RETRIEVAL_MIN_SCORE` |
| `VectorIndexMismatchError` | Cambió el embedder o la dimensión | Reindexar (ver §3) |
| `agy: timeout` | Modelo lento o 503 transitorio | Subir `UNSA_LLM_TIMEOUT_S`, fijar `UNSA_LLM_MODEL` más rápido, usar `UNSA_LLM_FALLBACK_MODELS` |
| `LLMError` por API key | Falta la clave del proveedor | Definir `UNSA_<PROVEEDOR>_API_KEY` |
| Una fuente da 0 páginas o errores | robots.txt, bloqueo anti-bot o estructura cambiada | Revisar `/api/admin/reports`; probar `UNSA_FETCHER=scrapling` |
| PDF "sin contenido textual" | PDF escaneado | Aún sin OCR; conseguir la versión con texto |
| 401 en `/api/admin` | Token ausente o distinto | Enviar `Authorization: Bearer $UNSA_ADMIN_TOKEN` |
| 429 en el chat | Límite de tasa por IP | Esperar, o ajustar el límite en `create_app` |
| El frontend no conecta | CORS o `PUBLIC_API_URL` | Añadir el origen a `UNSA_CORS_ORIGINS` |

## 9. Producción: lista de verificación

- [ ] `UNSA_ADMIN_TOKEN` largo y secreto; `/admin` detrás de HTTPS.
- [ ] `UNSA_CORS_ORIGINS` limitado al dominio del portal.
- [ ] Embeddings reales (no `hashing`) y LLM de pago o aprobado por la universidad.
- [ ] Fuentes reales verificadas y autorización de la UNSA para rastrearlas.
- [ ] Volumen `data/` respaldado.
- [ ] Umbral de abstención calibrado con un set de evaluación.
- [ ] Aviso visible: *"Asistente informativo. Para trámites oficiales, consulte en Secretaría."*
- [ ] Revisión humana de cambios en reglamentos y TUPA antes de confiar en ellos.
