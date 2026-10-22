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

### Ejecución local con `agy` como LLM (sin API key)

`agy` es el CLI de Antigravity; el sistema lo invoca como subproceso. Requisitos: `agy` en el `PATH`
(o `UNSA_AGY_BIN` con la ruta) y estar autenticado en él, según su propia configuración.
Comprobar: `agy models`.

El valor por defecto del código sigue siendo `fake` (para que las pruebas corran sin red). Para
usar `agy` como predeterminado en local:

```bash
make install                 # venv + dependencias + .env (desde .env.example)
# en .env:  UNSA_LLM_PROVIDER=agy
make ingest                  # indexa web + data/raw
make chat                    # prueba en terminal
make dev                     # backend :8000 + frontend :5173
```

El Makefile ya fija `UNSA_LLM_PROVIDER=agy` por defecto (`make backend LLM=gemini` lo cambia), así
que con `make` no hace falta tocar `.env`. Sin Makefile: `unsa-mind agy "pregunta"`, o
`UNSA_LLM_PROVIDER=agy unsa-mind serve`.

Objetivos del Makefile (`make help` los lista): `install`, `backend`, `frontend`, `dev` (ambos),
`ingest`, `chat`, `status`, `test`, `check-web`, `build-web`, `docker-up`, `docker-down`. Se pueden
levantar por separado: `make backend` en una terminal y `make frontend` en otra.
Variables: `LLM` (def. `agy`), `HOST` (`0.0.0.0`), `PORT` (`8000`), `WEB_PORT` (`5173`).

#### Parámetros configurables

Todos se definen en `.env` o como variable de entorno, con el prefijo `UNSA_`. Los que son listas
llevan JSON (`UNSA_CORS_ORIGINS='["http://localhost:5173"]'`).

| Variable | Defecto | Descripción |
|---|---|---|
| `UNSA_LLM_PROVIDER` | `fake` | `fake`, `claude`, `gemini`, `openrouter`, `agy` |
| `UNSA_LLM_MODEL` | proveedor | Modelo; con `agy` el defecto es `claude-sonnet-5-5-medium` (ver `agy models`) |
| `UNSA_LLM_FALLBACK_MODELS` | `[]` | Cadena de respaldo ante fallos transitorios |
| `UNSA_LLM_TIMEOUT_S` | `120` | Tiempo máximo por turno (`agy` puede tardar ~10 s o más) |
| `UNSA_AGY_BIN` | `agy` | Ejecutable de agy |
| `UNSA_ANTHROPIC_API_KEY` · `UNSA_GEMINI_API_KEY` · `UNSA_OPENROUTER_API_KEY` | — | Claves de los proveedores de pago |
| `UNSA_EMBEDDER_PROVIDER` | `hashing` | `hashing` (offline, pruebas), `local` (BGE-M3, **recomendado**), `gemini`, `openai_compat` (ver §3) |
| `UNSA_EMBEDDER_MODEL` | proveedor | Con `local`: `BAAI/bge-m3`; con `gemini`: `gemini-embedding-001` |
| `UNSA_EMBEDDER_DIMENSION` | `512` | Debe coincidir con el modelo (BGE-M3: `1024`; `hashing`: libre) |
| `UNSA_EMBEDDER_BASE_URL` · `UNSA_EMBEDDER_API_KEY` | — | Solo `openai_compat` |
| `UNSA_VECTOR_STORE` | `sqlite` | `sqlite`, `qdrant`, `memory` |
| `UNSA_REPOSITORY` | `sqlite` | `sqlite` o `memory` (fuentes, documentos, informes) |
| `UNSA_DATA_DIR` | `data` | Carpeta de `unsa_mind.db` y `vectors.db` |
| `UNSA_RAW_DIR` | `data/raw` | Única carpeta desde la que se leen documentos locales |
| `UNSA_OCR_PROVIDER` | `none` | `tesseract` (liviano, libros) o `agy` (visión) para PDF escaneados; DOCX/PPTX/XLSX con el extra `ocr` |
| `UNSA_OCR_LANG` · `UNSA_TESSERACT_BIN` | `spa` · `tesseract` | Solo Tesseract: idioma(s) (`spa+eng`) y ejecutable |
| `UNSA_OCR_MODEL` | `gemini-3.8-flash-medium` | Solo `agy`: modelo de visión de `agy models` |
| `UNSA_OCR_TIMEOUT_S` · `UNSA_OCR_MAX_PAGES` · `UNSA_OCR_CONCURRENCY` | `120` · `0` (auto: agy 80, tesseract 1000) · `3` | Límite por página · páginas por PDF (se comprueba antes de empezar) · páginas en paralelo |
| `UNSA_QDRANT_URL` · `UNSA_QDRANT_API_KEY` · `UNSA_QDRANT_COLLECTION` | `http://localhost:6333` · — · `unsa_chunks` | Solo con `qdrant` |
| `UNSA_FETCHER` | `httpx` | `httpx` o `scrapling` |
| `UNSA_USER_AGENT` | `UnsaMindBot/0.1 …` | User-Agent del rastreo; configure un contacto real |
| `UNSA_REQUEST_DELAY_S` | `1.0` | Espera entre peticiones al mismo dominio |
| `UNSA_RESPECT_ROBOTS` | `true` | Respetar robots.txt |
| `UNSA_SOURCES_FILE` | `config/sources.yaml` | Catálogo semilla de fuentes |
| `UNSA_SCHEDULE_ENABLED` · `UNSA_SCHEDULE_INTERVAL_MINUTES` · `UNSA_SCHEDULE_CRON` | `true` · `1440` · — | Schedule inicial (luego se cambia en caliente) |
| `UNSA_RUN_SCHEDULER` | `true` | Scheduler embebido en `serve` |
| `UNSA_RETRIEVAL_CANDIDATES` · `UNSA_RETRIEVAL_TOP_N` · `UNSA_RETRIEVAL_MIN_SCORE` | `20` · `6` · `0.15` | Recuperación y umbral de abstención |
| `UNSA_HOST` · `UNSA_PORT` | `0.0.0.0` · `8000` | Dirección de `serve` |
| `UNSA_ADMIN_TOKEN` | — | Token de `/api/admin`; sin él queda abierto (solo desarrollo) |
| `UNSA_CORS_ORIGINS` | `["http://localhost:5173"]` | Orígenes permitidos |
| `UNSA_PUBLIC_URL` | `http://localhost:8000` | URL que anuncia el Agent Card A2A |

Frontend: `API_PROXY_TARGET` (def. `http://localhost:8000`) indica a Vite a qué backend redirigir
`/api` en desarrollo; el Makefile lo deriva de `PORT`.

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
| `hashing` | **por defecto** (`UNSA_EMBEDDER_DIMENSION=512`) | Offline, **léxico**; solo para pruebas y para correr sin descargar modelos |
| `gemini` | `UNSA_EMBEDDER_PROVIDER=gemini` + `UNSA_GEMINI_API_KEY` | Buena calidad multilingüe |
| `openai_compat` | `UNSA_EMBEDDER_BASE_URL`, `UNSA_EMBEDDER_API_KEY`, `UNSA_EMBEDDER_MODEL` | OpenRouter, OpenAI, Ollama, vLLM |
| `local` | **Recomendado.** `make install-bge` (o `pip install -e ".[local-embeddings]"`), luego `UNSA_EMBEDDER_PROVIDER=local` y `UNSA_EMBEDDER_DIMENSION=1024` | BGE-M3, multilingüe, sin salir a internet. Arrastra PyTorch y descarga el modelo (unos GB) la primera vez. Sin el extra falla con un mensaje claro |

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

### Documentos locales (carpeta `data/raw`)

Además de la web, se pueden indexar archivos del disco: copie **PDF, HTML, TXT o MD** a `data/raw/`
(se recorre recursivamente; se ignoran archivos ocultos y otros formatos) y ejecute
`unsa-mind ingest`. La fuente `documentos-locales` de `config/sources.yaml` ya apunta a esa carpeta.

- Para otra subcarpeta: `unsa-mind sources add normas raw:normas --authority high`. La URL puede ser
  `raw:` / `raw:subcarpeta` (relativa a `UNSA_RAW_DIR`), una ruta o `file://`; **siempre debe quedar
  dentro de `UNSA_RAW_DIR`**, cualquier otra ruta se rechaza.
- Pasan por el mismo pipeline que la web: hash (solo se reindexa lo que cambió), versionado y
  chunking por artículo. El título de un `.txt`/`.md` es su primer `# encabezado` o el nombre del archivo.
- Limitaciones: si borra un archivo de la carpeta, sus chunks siguen activos (elimine la fuente o
  reindexe).

#### PDF escaneados y Office (OCR)

Por defecto un PDF sin texto extraíble falla con "probablemente escaneado". Hay dos proveedores:

| | `tesseract` (liviano) | `agy` (modelo de visión) |
|---|---|---|
| Para | **Libros y volúmenes grandes** | Documentos cortos, con tablas o mala calidad |
| Instalación | `make install-ocr-light` + `sudo apt install tesseract-ocr tesseract-ocr-spa` | `make install-ocr` + `agy` en el `PATH` |
| Velocidad | ~1–3 s por página (CPU), sin cuota ni red | ~7 s por página, variable (cuota y latencia) |
| Tope por defecto | 1000 páginas | 80 páginas |
| Calidad | Buena en impresos limpios; peor en tablas, sellos y manuscritos | Mejor en diseños complejos; puede errar en cifras y fechas |
| DOCX/PPTX/XLSX | Con `make install-ocr` | Con `make install-ocr` |

```bash
# Libros (liviano):
make install-ocr-light && sudo apt install tesseract-ocr tesseract-ocr-spa
# en .env:  UNSA_OCR_PROVIDER=tesseract   (UNSA_OCR_LANG=spa; "spa+eng" si hay inglés)

# Documentos cortos o complejos (modelo de visión):
make install-ocr
# en .env:  UNSA_OCR_PROVIDER=agy   UNSA_OCR_MODEL=gemini-3.8-flash-medium
#           (el esfuerzo low|medium|high va en el id del modelo; ver `agy models`)

unsa-mind ingest --source documentos-locales
```

Si falta el binario o el idioma de Tesseract, el arranque falla con un mensaje que dice qué instalar.
Los tests de Tesseract usan un binario simulado: **no se ha validado la calidad con Tesseract real
sobre documentos de la UNSA**; haga una prueba con 2 o 3 libros antes de ingestar un lote.

- Solo se usa OCR cuando el PDF **no tiene texto**; los PDF con texto siguen por el parser propio
  (reconoce Título/Capítulo/Artículo). El texto transcrito pasa por la misma limpieza y estructura, y
  el documento queda con `"ocr": true` en sus metadatos.
- Cada página se transcribe con una llamada, `UNSA_OCR_CONCURRENCY` (3) en paralelo. Con `agy`
  corre con el modelo en `--sandbox`, una carpeta temporal aislada y un prompt que trata el contenido
  de la imagen como datos; los fallos transitorios (503/429) se reintentan. Tesseract se renderiza a
  300 dpi y se lanza con un solo hilo por proceso (el paralelismo lo da la concurrencia).
- **Un documento con alguna página sin transcribir no se indexa a medias**: falla con "OCR
  incompleto" y se reintenta en el siguiente ciclo. `UNSA_OCR_MAX_PAGES` acota las páginas por PDF y
  se comprueba **antes** de transcribir nada (0 = automático: 80 con `agy`, 1000 con Tesseract);
  `UNSA_OCR_TIMEOUT_S` (120) es el límite por página.
- Con `agy`, el resultado de cada página se guarda en `data/ocr_cache/`: si el documento falla a
  mitad, al reintentar solo se repiten las páginas pendientes (Tesseract es tan rápido que no usa caché).
- El OCR puede equivocarse en cifras y fechas: **revise siempre con
  `/api/admin/documents/{doc_id}/chunks`** los documentos escaneados antes de confiar en ellos.
- La ingesta de un escaneado es lenta; en el servidor corre en un hilo aparte y no bloquea la API.

### Ver qué se indexó

`GET /api/admin/documents` y `GET /api/admin/documents/{doc_id}/chunks` (solo lectura; ver
[API.md](API.md)). También se puede mirar directamente `data/unsa_mind.db` (tabla `documents`) y
`data/vectors.db` (tabla `chunks`) con `sqlite3`. No se guarda el HTML/PDF original, solo el texto
troceado.

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
