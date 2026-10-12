"""Entidades y objetos de valor del dominio. No dependen de ninguna librería externa."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


class Authority(str, Enum):
    """Peso normativo de una fuente: un reglamento prevalece sobre una noticia."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def boost(self) -> float:
        return {"high": 1.0, "medium": 0.85, "low": 0.7}[self.value]


class Intent(str, Enum):
    ADMISSION = "admision"
    GRADUATE = "posgrado"
    AGREEMENTS = "convenios"
    PROCEDURES = "tramites"
    GENERAL = "general"
    OUT_OF_SCOPE = "fuera_de_alcance"


class DocKind(str, Enum):
    HTML = "html"
    PDF = "pdf"


@dataclass(frozen=True)
class Schedule:
    """Política de actualización. `cron` (5 campos) tiene prioridad sobre `interval_minutes`."""

    enabled: bool = True
    interval_minutes: int = 1440
    cron: str | None = None


@dataclass
class Source:
    """Fuente a rastrear (una URL semilla y cómo seguir enlaces)."""

    id: str
    name: str
    url: str
    kind: DocKind = DocKind.HTML
    authority: Authority = Authority.MEDIUM
    metadata: dict[str, Any] = field(default_factory=dict)  # facultad, tipo_doc, nivel...
    follow_links: bool = False
    link_pattern: str | None = None  # regex de enlaces a seguir
    max_pages: int = 20
    interval_minutes: int | None = None  # None => usa el schedule global
    enabled: bool = True
    last_run_at: datetime | None = None


@dataclass(frozen=True)
class RawDocument:
    source_id: str
    url: str
    content_type: str
    body: bytes
    fetched_at: datetime = field(default_factory=utcnow)
    links: tuple[str, ...] = ()  # enlaces descubiertos (solo HTML)


@dataclass(frozen=True)
class ParsedDocument:
    source_id: str
    url: str
    title: str
    markdown: str
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=utcnow)


@dataclass
class DocumentRecord:
    """Versión conocida de un documento (por URL)."""

    doc_id: str
    source_id: str
    url: str
    title: str
    content_hash: str
    version: int
    fetched_at: datetime
    active: bool = True


@dataclass
class Chunk:
    id: str
    doc_id: str
    source_id: str
    url: str
    title: str
    text: str  # texto original (lo que se cita)
    context: str = ""  # contexto antepuesto antes de embeber (Contextual Retrieval)
    section: str = ""  # ruta jerárquica: "Reglamento > Cap. III > Art. 14"
    position: int = 0
    authority: Authority = Authority.MEDIUM
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    active: bool = True
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def indexable_text(self) -> str:
        return f"{self.context}\n{self.text}".strip() if self.context else self.text


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class Citation:
    title: str
    section: str
    url: str
    updated_at: datetime | None = None


@dataclass
class Answer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    abstained: bool = False
    intent: Intent = Intent.GENERAL
    data_as_of: datetime | None = None


@dataclass
class SourceReport:
    source_id: str
    pages_fetched: int = 0
    documents_new: int = 0
    documents_changed: int = 0
    documents_unchanged: int = 0
    chunks_indexed: int = 0
    chunks_deactivated: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class UpdateReport:
    started_at: datetime
    finished_at: datetime | None = None
    sources: list[SourceReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(not s.errors for s in self.sources)
