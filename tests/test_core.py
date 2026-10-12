"""Pruebas del núcleo con adaptadores en memoria (sin red)."""

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
from unsa_mind.domain.entities import Authority, ParsedDocument, RawDocument, Source, sha256

PAGE = {"text": "# Reserva de matrícula\n\nArtículo 14. La reserva de matrícula se solicita ante la "
        "Secretaría Académica dentro de los primeros quince días del semestre, adjuntando recibo de pago."}


class FakeFetcher:
    async def fetch(self, url, *, source_id):
        return RawDocument(source_id, url, "text/html", PAGE["text"].encode())


class FakeParser:
    def supports(self, ct):
        return True

    def parse(self, raw, *, base_metadata):
        md = raw.body.decode()
        return ParsedDocument(raw.source_id, raw.url, "Reglamento de Matrícula", md, sha256(md), base_metadata)


@pytest.fixture
def stack():
    emb, store = HashingEmbedder(), InMemoryVectorStore()
    docs, sources, settings = InMemoryDocumentRepository(), InMemorySourceRepository(), InMemorySettingsRepository()
    ingest = IngestSource(fetcher=FakeFetcher(), parsers=[FakeParser()], embedder=emb, vector_store=store, documents=docs)
    cycle = RunUpdateCycle(sources=sources, settings=settings, ingest=ingest)
    ask = AskQuestion(llm=FakeLLM(), embedder=emb, vector_store=store)
    return sources, cycle, ask, store, docs


async def test_ingest_is_idempotent_and_versions(stack):
    sources, cycle, _, store, docs = stack
    await sources.save_source(Source("reg", "Reglamento", "https://unsa.test/reg", authority=Authority.HIGH))
    r1 = await cycle.execute()
    assert r1.sources[0].documents_new == 1 and await store.count() >= 1
    r2 = await cycle.execute()
    assert r2.sources[0].documents_unchanged == 1 and r2.sources[0].chunks_indexed == 0
    PAGE["text"] += "\n\nSe aplica un cargo adicional por extemporaneidad."
    r3 = await cycle.execute()
    assert r3.sources[0].documents_changed == 1 and r3.sources[0].chunks_deactivated >= 1
    assert len(await docs.list_documents(active_only=False)) == 2


async def test_answer_has_citations_and_abstains(stack):
    sources, cycle, ask, *_ = stack
    await sources.save_source(Source("reg", "Reglamento", "https://unsa.test/reg"))
    await cycle.execute()
    a = await ask.execute("¿Cómo solicito la reserva de matrícula?")
    assert not a.abstained and a.citations and a.citations[0].url == "https://unsa.test/reg"
    b = await ask.execute("¿Cuál es el costo de la maestría en astrofísica?")
    assert b.abstained
    c = await ask.execute("dame una receta de pastel")
    assert c.abstained
