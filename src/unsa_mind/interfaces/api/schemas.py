"""Esquemas Pydantic v2 del contrato REST."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from unsa_mind.domain.entities import Authority, DocKind, Source
from unsa_mind.interfaces.common import iso, validate_cron


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=50)
    filters: dict[str, Any] | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("el mensaje no puede estar vacío")
        return v


class CitationOut(BaseModel):
    title: str
    section: str
    url: str
    updated_at: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    abstained: bool
    intent: str
    data_as_of: str | None = None


class FeedbackRequest(BaseModel):
    message_id: str | None = Field(default=None, max_length=128)
    value: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)


class HealthResponse(BaseModel):
    status: str
    llm: str
    vector_chunks: int
    next_update: str | None = None


class ScheduleIn(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(default=1440, ge=1)
    cron: str | None = None

    @field_validator("cron")
    @classmethod
    def _cron(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        try:
            validate_cron(v.strip())
        except ValueError as exc:
            raise ValueError(f"cron inválido: {exc}") from exc
        return v.strip()


class ScheduleOut(ScheduleIn):
    next_run: str | None = None


class SourceIn(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str | None = None
    url: str = Field(min_length=1)
    kind: DocKind = DocKind.HTML
    authority: Authority = Authority.MEDIUM
    metadata: dict[str, Any] = Field(default_factory=dict)
    follow_links: bool = False
    link_pattern: str | None = None
    max_pages: int = Field(default=20, ge=1, le=1000)
    interval_minutes: int | None = Field(default=None, ge=1)
    enabled: bool = True

    @model_validator(mode="after")
    def _default_name(self) -> "SourceIn":
        if not self.name:
            self.name = self.id
        return self

    def to_entity(self, last_run_at=None) -> Source:
        return Source(
            id=self.id,
            name=self.name or self.id,
            url=self.url,
            kind=self.kind,
            authority=self.authority,
            metadata=self.metadata,
            follow_links=self.follow_links,
            link_pattern=self.link_pattern,
            max_pages=self.max_pages,
            interval_minutes=self.interval_minutes,
            enabled=self.enabled,
            last_run_at=last_run_at,
        )


class SourceOut(SourceIn):
    last_run_at: str | None = None

    @classmethod
    def from_entity(cls, s: Source) -> "SourceOut":
        return cls(
            id=s.id,
            name=s.name,
            url=s.url,
            kind=s.kind,
            authority=s.authority,
            metadata=s.metadata,
            follow_links=s.follow_links,
            link_pattern=s.link_pattern,
            max_pages=s.max_pages,
            interval_minutes=s.interval_minutes,
            enabled=s.enabled,
            last_run_at=iso(s.last_run_at),
        )


class UpdateRequest(BaseModel):
    force: bool = False
    only: list[str] | None = None


class DocumentOut(BaseModel):
    doc_id: str
    source_id: str
    url: str
    title: str
    version: int
    content_hash: str
    fetched_at: str | None = None
    active: bool


class DocumentPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DocumentOut]


class ChunkOut(BaseModel):
    id: str
    position: int
    section: str
    text: str
    context: str
    authority: str
    metadata: dict[str, Any]
    active: bool
    updated_at: str | None = None


class DocumentChunks(BaseModel):
    document: DocumentOut
    chunks: list[ChunkOut]


class StatsOut(BaseModel):
    chunks_active: int
    documents_active: int
    sources: int
