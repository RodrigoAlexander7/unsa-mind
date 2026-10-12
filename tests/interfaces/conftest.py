"""Fixtures de interfaces: Container armado a mano con adaptadores en memoria."""

import asyncio
import json

import pytest

from unsa_mind.adapters.memory import (
    FakeLLM,
    HashingEmbedder,
    InMemoryDocumentRepository,
    InMemorySettingsRepository,
    InMemorySourceRepository,
    InMemoryVectorStore,
)
from unsa_mind.application.use_cases.ask_question import AskQuestion
from unsa_mind.application.use_cases.ingest_source import IngestSource
from unsa_mind.application.use_cases.run_update_cycle import RunUpdateCycle
from unsa_mind.config.container import Container
from unsa_mind.config.settings import Settings
from unsa_mind.domain.entities import (
    Authority,
    ParsedDocument,
    RawDocument,
    Schedule,
    Source,
    sha256,
)

PAGE = (
    "# Reserva de matrícula\n\nArtículo 14. La reserva de matrícula se solicita ante la "
    "Secretaría Académica dentro de los primeros quince días del semestre, adjuntando recibo de pago."
)


class FakeFetcher:
    async def fetch(self, url, *, source_id):
        return RawDocument(source_id, url, "text/html", PAGE.encode())


class FakeParser:
    def supports(self, ct):
        return True

    def parse(self, raw, *, base_metadata):
        md = raw.body.decode()
        return ParsedDocument(raw.source_id, raw.url, "Reglamento de Matrícula", md, sha256(md), base_metadata)


class FakeScheduler:
    def __init__(self):
        self.started_with = None
        self.job = None
        self.applied: list[Schedule] = []
        self.stopped = False

    def start(self, job, schedule):
        self.job, self.started_with = job, schedule

    def apply(self, schedule):
        self.applied.append(schedule)

    def shutdown(self):
        self.stopped = True

    def next_run(self):
        sched = self.applied[-1] if self.applied else self.started_with
        return "2030-01-01T03:00:00+00:00" if sched and sched.enabled else None


def make_container(tmp_path, admin_token=None, seed=True, **settings_kw) -> Container:
    settings = Settings(
        _env_file=None,
        admin_token=admin_token,
        data_dir=tmp_path,
        sources_file=tmp_path / "no-sources.yaml",
        cors_origins=["http://localhost:5173"],
        **settings_kw,
    )
    emb, store = HashingEmbedder(), InMemoryVectorStore()
    docs, sources = InMemoryDocumentRepository(), InMemorySourceRepository()
    repo = InMemorySettingsRepository(Schedule(True, 60, None))
    ingest = IngestSource(fetcher=FakeFetcher(), parsers=[FakeParser()], embedder=emb,
                          vector_store=store, documents=docs)
    llm = FakeLLM()
    c = Container(
        settings=settings, llm=llm, embedder=emb, vector_store=store, sources=sources,
        documents=docs, settings_repo=repo, fetcher=FakeFetcher(), parsers=[FakeParser()],
        scheduler=FakeScheduler(), ingest=ingest,
        update_cycle=RunUpdateCycle(sources=sources, settings=repo, ingest=ingest),
        ask=AskQuestion(llm=llm, embedder=emb, vector_store=store),
    )
    if seed:
        async def _seed():
            await sources.save_source(
                Source("reg", "Reglamento", "https://unsa.test/reg", authority=Authority.HIGH)
            )
            await c.update_cycle.execute()
        asyncio.run(_seed())
    return c


@pytest.fixture
def container(tmp_path):
    return make_container(tmp_path)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        event, data = "message", None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        out.append((event, data))
    return out
