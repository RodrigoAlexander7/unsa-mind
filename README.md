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

Atajos: `make install`, `make dev` (backend + frontend; LLM `agy` por defecto), `make backend`,
`make frontend`, `make ingest`, `make help`. Documentos locales: copie PDF/HTML/TXT/MD a `data/raw/`
y ejecute `make ingest`.

> Con `UNSA_LLM_PROVIDER=fake` y `UNSA_EMBEDDER_PROVIDER=hashing` (valores por defecto) todo corre
> offline, útil para probar; el embedder `hashing` es solo léxico.
>
> **Recomendado para calidad real: embeddings BGE-M3** (multilingüe, local, sin API key):
> ```bash
> make install-bge        # o: pip install -e ".[local-embeddings]"  (arrastra PyTorch)
> # en .env:  UNSA_EMBEDDER_PROVIDER=local   UNSA_EMBEDDER_DIMENSION=1024
> rm -rf data/*.db && unsa-mind ingest   # cambiar de embedder exige reindexar
> ```
> El modelo (unos GB) se descarga la primera vez. Más opciones y un LLM real:
> [guía](docs/OPERACION.md#2-elegir-proveedor-de-llm).

## Ingesta paso a paso (documentos locales en `data/raw/`)
> Tambien se puede hacer 
> .venv/bin/unsa-mind ingest --source documentos-locales

1. **Instalar y configurar.** `make install` (crea `.venv`, instala dependencias y copia `.env`).
   Opcional pero recomendado para evaluar calidad: BGE-M3 (ver arriba) y `UNSA_LLM_PROVIDER=agy`.
2. **Copiar los archivos** a `data/raw/` (se recorre recursivamente; se ignoran los ocultos).
   Formatos: **PDF con texto, Markdown, TXT y HTML**; con el OCR activado (paso 2b) también
   **PDF escaneados, DOCX, PPTX y XLSX**. Para otra subcarpeta con otra autoridad o metadatos, añada
   una fuente: `unsa-mind sources add normas raw:normas --authority high` (`raw:` es relativo a
   `UNSA_RAW_DIR`, por defecto `data/raw`; una ruta fuera de esa carpeta se rechaza).
   - **2b. (Opcional) OCR de PDF escaneados** (solo se usa si el PDF no tiene texto):
     - **Libros / volúmenes grandes (liviano):** `make install-ocr-light`, `sudo apt install
       tesseract-ocr tesseract-ocr-spa` y en `.env` `UNSA_OCR_PROVIDER=tesseract`. ~1–3 s por página.
     - **Documentos cortos o complejos (modelo de visión):** `make install-ocr` y
       `UNSA_OCR_PROVIDER=agy` (`UNSA_OCR_MODEL=gemini-3.8-flash-medium`). ~7 s por página.
     - `make install-ocr` también habilita DOCX/PPTX/XLSX. Comparativa y límites en
       [docs/OPERACION.md](docs/OPERACION.md#4-gestionar-fuentes). Revise siempre el resultado en el paso 4.
3. **Ingestar** solo esa fuente:
   ```bash
   unsa-mind ingest --source documentos-locales      # o: make ingest (todas las fuentes)
   ```
   Imprime por fuente: páginas leídas, documentos nuevos/cambiados/sin cambios y chunks indexados;
   los archivos que fallan aparecen con `!` y el motivo.
4. **Verificar lo indexado:**
   ```bash
   unsa-mind status
   curl -s localhost:8000/api/admin/documents                 # con `make backend` en marcha
   curl -s localhost:8000/api/admin/documents/<doc_id>/chunks  # texto troceado, en orden
   ```
   (con `UNSA_ADMIN_TOKEN` definido añada `-H "Authorization: Bearer $TOKEN"`). También se puede
   consultar `data/unsa_mind.db` (tabla `documents`) y `data/vectors.db` (tabla `chunks`).
5. **Probar preguntas:** `unsa-mind ask "su pregunta" --llm agy`. Revise las citas (título, sección,
   fecha) y que se abstenga cuando la respuesta no esté en los documentos.
6. **Iterar.** Reejecutar `ingest` solo reindexa los archivos que cambiaron (detección por hash).
   Para empezar de cero —obligatorio si cambia de embedder— use
   `rm -f data/*.db && unsa-mind ingest`.

Limitaciones actuales: sin el OCR activado, los **PDF escaneados no se indexan** (el informe muestra
"El PDF no contiene texto extraíble") y DOCX/PPTX/XLSX tampoco; el OCR por visión puede errar en
cifras y fechas; y borrar un archivo de `data/raw/` no retira sus chunks del índice. Detalle en
[docs/OPERACION.md](docs/OPERACION.md#4-gestionar-fuentes).

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
