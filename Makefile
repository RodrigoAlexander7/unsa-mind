# unsa-mind: atajos para desarrollo local. `make help` lista los objetivos.
#
# El LLM por defecto en local es `agy` (sin API key). Cámbialo por invocación:
#   make backend LLM=gemini        make chat LLM=fake
# El resto de parámetros se leen de .env (UNSA_*); ver docs/OPERACION.md §2.

LLM  ?= agy
HOST ?= 0.0.0.0
PORT ?= 8000
WEB_PORT ?= 5173

VENV := .venv
ifeq ($(OS),Windows_NT)
BIN := $(VENV)/Scripts
else
BIN := $(VENV)/bin
endif

export UNSA_LLM_PROVIDER := $(LLM)
# Para que el proxy del frontend apunte al backend elegido.
export API_PROXY_TARGET ?= http://localhost:$(PORT)

.DEFAULT_GOAL := help
.PHONY: help install install-api install-bge install-ocr-light install-ocr install-web env backend frontend dev ingest chat status \
        test check-web build-web docker-up docker-down

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Variables: LLM=$(LLM) HOST=$(HOST) PORT=$(PORT) WEB_PORT=$(WEB_PORT)"

# ---- instalación ---------------------------------------------------------------------
install: install-api install-web env ## Instala backend, frontend y crea .env si falta

install-api: ## Crea .venv e instala el backend (ligero; embeddings hashing por defecto)
	python3 -m venv $(VENV)
	$(BIN)/pip install -e ".[dev]"

install-bge: ## Añade embeddings BGE-M3 (PyTorch, pesado); luego UNSA_EMBEDDER_PROVIDER=local
	$(BIN)/pip install -e ".[local-embeddings]"
	@echo "Configure en .env: UNSA_EMBEDDER_PROVIDER=local y UNSA_EMBEDDER_DIMENSION=1024, y reindexe."

install-ocr-light: ## OCR liviano para libros escaneados con Tesseract (requiere tesseract-ocr-spa del sistema)
	$(BIN)/pip install -e ".[ocr-light]"
	@echo "Instale el binario: sudo apt install tesseract-ocr tesseract-ocr-spa"
	@echo "Configure en .env: UNSA_OCR_PROVIDER=tesseract"

install-ocr: ## OCR con modelo de visión (agy) + Office (MarkItDown); luego UNSA_OCR_PROVIDER=agy
	$(BIN)/pip install -e ".[ocr]"
	@echo "Configure en .env: UNSA_OCR_PROVIDER=agy (requiere agy en el PATH)."

install-web: ## Instala las dependencias del frontend (pnpm)
	cd web && pnpm install

env: ## Crea .env a partir de .env.example si no existe
	@test -f .env || (cp .env.example .env && echo ".env creado: revísalo")

# ---- ejecución (cada proceso por separado) -------------------------------------------
backend: ## Levanta API REST + A2A + scheduler (PORT, por defecto 8000)
	$(BIN)/unsa-mind serve --host $(HOST) --port $(PORT)

frontend: ## Levanta el frontend SvelteKit (WEB_PORT, por defecto 5173)
	cd web && pnpm dev --port $(WEB_PORT)

dev: ## Levanta backend y frontend a la vez (Ctrl+C detiene ambos)
	$(MAKE) -j2 backend frontend

# ---- operación -----------------------------------------------------------------------
ingest: ## Rastrea las fuentes (web y data/raw) e indexa lo que cambió
	$(BIN)/unsa-mind ingest

chat: ## Chat interactivo en terminal con el LLM elegido
	$(BIN)/unsa-mind chat

status: ## Estado: chunks, documentos, fuentes y último ciclo
	$(BIN)/unsa-mind status

# ---- calidad -------------------------------------------------------------------------
test: ## Ejecuta los tests del backend (sin red)
	$(BIN)/python -m pytest -q

check-web: ## Verifica tipos y tests del frontend
	cd web && pnpm check && pnpm test

build-web: ## Compila el frontend para producción
	cd web && pnpm build

# ---- contenedores --------------------------------------------------------------------
docker-up: ## Levanta todo con Docker Compose (api :8000, web :3000)
	docker compose up --build

docker-down: ## Detiene los contenedores
	docker compose down
