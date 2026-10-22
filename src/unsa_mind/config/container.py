"""Raíz de composición: el ÚNICO lugar que conoce adaptadores concretos.

Las factorías (`adapters/*/factory.py`) eligen la implementación según `Settings`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from unsa_mind.application.ports import (
    DocumentRepositoryPort,
    EmbedderPort,
    FetcherPort,
    LLMPort,
    ParserPort,
    RerankerPort,
    SchedulerPort,
    SettingsRepositoryPort,
    SourceRepositoryPort,
    VectorStorePort,
)
from unsa_mind.application.use_cases.ask_question import AskConfig, AskQuestion
from unsa_mind.application.use_cases.ingest_source import IngestSource
from unsa_mind.application.use_cases.run_update_cycle import RunUpdateCycle
from unsa_mind.config.settings import Settings, get_settings
from unsa_mind.domain.entities import Authority, DocKind, Schedule, Source


@dataclass
class Container:
    settings: Settings
    llm: LLMPort
    embedder: EmbedderPort
    vector_store: VectorStorePort
    sources: SourceRepositoryPort
    documents: DocumentRepositoryPort
    settings_repo: SettingsRepositoryPort
    fetcher: FetcherPort
    parsers: list[ParserPort]
    scheduler: SchedulerPort
    ask: AskQuestion
    ingest: IngestSource
    update_cycle: RunUpdateCycle
    reranker: RerankerPort | None = None


def build_container(settings: Settings | None = None, *, with_scheduler: bool = True) -> Container:
    from unsa_mind.adapters.embeddings.factory import build_embedder
    from unsa_mind.adapters.llm.factory import build_llm
    from unsa_mind.adapters.persistence.factory import build_repositories
    from unsa_mind.adapters.scheduling.factory import build_scheduler
    from unsa_mind.adapters.scraping.factory import build_fetcher, build_parsers
    from unsa_mind.adapters.vectorstore.factory import build_vector_store

    s = settings or get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.raw_dir.mkdir(parents=True, exist_ok=True)

    llm = build_llm(s)
    embedder = build_embedder(s)
    store = build_vector_store(s, embedder)
    sources, documents, settings_repo = build_repositories(s)
    fetcher = build_fetcher(s)
    parsers = build_parsers(s)
    scheduler = build_scheduler(s)

    ingest = IngestSource(
        fetcher=fetcher,
        parsers=parsers,
        embedder=embedder,
        vector_store=store,
        documents=documents,
    )
    return Container(
        settings=s,
        llm=llm,
        embedder=embedder,
        vector_store=store,
        sources=sources,
        documents=documents,
        settings_repo=settings_repo,
        fetcher=fetcher,
        parsers=parsers,
        scheduler=scheduler,
        ingest=ingest,
        update_cycle=RunUpdateCycle(sources=sources, settings=settings_repo, ingest=ingest),
        ask=AskQuestion(
            llm=llm,
            embedder=embedder,
            vector_store=store,
            config=AskConfig(
                candidates=s.retrieval_candidates,
                top_n=s.retrieval_top_n,
                min_score=s.retrieval_min_score,
            ),
        ),
    )


def load_sources_file(path: Path) -> list[Source]:
    """Lee `config/sources.yaml` (semilla del catálogo de fuentes)."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[Source] = []
    for item in data.get("sources", []):
        out.append(
            Source(
                id=item["id"],
                name=item.get("name", item["id"]),
                url=item["url"],
                kind=DocKind(item.get("kind", "html")),
                authority=Authority(item.get("authority", "medium")),
                metadata=item.get("metadata", {}),
                follow_links=item.get("follow_links", False),
                link_pattern=item.get("link_pattern"),
                max_pages=item.get("max_pages", 20),
                interval_minutes=item.get("interval_minutes"),
                enabled=item.get("enabled", True),
            )
        )
    return out


async def bootstrap(c: Container) -> None:
    """Siembra fuentes del YAML (sin pisar las editadas) y aplica el Schedule inicial."""
    existing = {s.id for s in await c.sources.list_sources()}
    for src in load_sources_file(c.settings.sources_file):
        if src.id not in existing:
            await c.sources.save_source(src)
    s = c.settings
    if not await c.settings_repo.has_schedule():
        await c.settings_repo.save_schedule(
            Schedule(s.schedule_enabled, s.schedule_interval_minutes, s.schedule_cron)
        )
