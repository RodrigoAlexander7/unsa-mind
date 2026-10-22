import pytest

from unsa_mind.adapters.memory import HashingEmbedder
from unsa_mind.adapters.vectorstore import (
    SqliteVectorStore,
    VectorIndexMismatchError,
    build_vector_store,
)
from unsa_mind.config.settings import Settings
from unsa_mind.domain.entities import Chunk

DIM = 256
TEXTS = {
    "c1": ("Reserva de matrícula", "La reserva de matrícula se solicita ante la Secretaría "
           "Académica dentro de los primeros quince días del semestre.", {"facultad": "ING"}),
    "c2": ("Admisión", "El examen de admisión ordinario se rinde en el campus universitario "
           "y requiere el pago de derechos.", {"facultad": "MED"}),
    "c3": ("Convenios", "Convenio marco con la universidad de Granada para movilidad estudiantil "
           "e intercambio de docentes.", {"facultad": "ING"}),
}


def _chunks():
    return [
        Chunk(id=cid, doc_id=f"doc-{cid}", source_id="s", url=f"https://x/{cid}", title=t,
              text=body, metadata=meta)
        for cid, (t, body, meta) in TEXTS.items()
    ]


async def _store(path, emb):
    store = SqliteVectorStore(path, emb.dimension)
    chunks = _chunks()
    await store.upsert(chunks, await emb.embed_documents([c.indexable_text for c in chunks]))
    return store


async def _search(store, emb, q, **kw):
    return await store.search(query_text=q, query_vector=await emb.embed_query(q), **kw)


async def test_lexical_exact_query(tmp_path):
    emb = HashingEmbedder(DIM)
    store = await _store(tmp_path / "v.db", emb)
    res = await _search(store, emb, "Secretaría Académica quince días", k=3)
    assert res[0].chunk.id == "c1"
    assert res[0].score > 0.5
    assert all(0.0 <= r.score <= 1.0 for r in res)


async def test_accent_insensitive(tmp_path):
    emb = HashingEmbedder(DIM)
    store = await _store(tmp_path / "v.db", emb)
    res = await _search(store, emb, "secretaria academica", k=3)
    assert res[0].chunk.id == "c1"


async def test_semantic_dense_only_candidate(tmp_path):
    # Sin coincidencia léxica en FTS pero con palabras compartidas vía hashing: el top debe ser c3.
    emb = HashingEmbedder(DIM)
    store = await _store(tmp_path / "v.db", emb)
    res = await _search(store, emb, "movilidad estudiantil universidad Granada", k=2)
    assert res[0].chunk.id == "c3"


async def test_unrelated_query_scores_low(tmp_path):
    emb = HashingEmbedder(DIM)
    store = await _store(tmp_path / "v.db", emb)
    res = await _search(store, emb, "receta de lomo saltado con papas", k=3)
    assert all(r.score < 0.15 for r in res)
    related = await _search(store, emb, "reserva de matrícula", k=1)
    assert related[0].score > 0.15


async def test_filters_and_special_chars(tmp_path):
    emb = HashingEmbedder(DIM)
    store = await _store(tmp_path / "v.db", emb)
    res = await _search(store, emb, "admisión examen", k=5, filters={"facultad": "ING"})
    assert res and all(r.chunk.metadata["facultad"] == "ING" for r in res)
    # la sintaxis FTS5 en la consulta no debe romper la búsqueda
    res = await _search(store, emb, 'matrícula" OR (NEAR* -x', k=3)
    assert isinstance(res, list)
    assert await _search(store, emb, "???", k=3) is not None


async def test_deactivate_keeps_rows(tmp_path):
    emb = HashingEmbedder(DIM)
    store = await _store(tmp_path / "v.db", emb)
    assert await store.deactivate_document("doc-c1") == 1
    assert await store.deactivate_document("doc-c1") == 0
    assert await store.count() == 2
    assert await store.count(active_only=False) == 3
    res = await _search(store, emb, "reserva de matrícula Secretaría", k=5)
    assert "c1" not in {r.chunk.id for r in res}


async def test_upsert_replaces_and_reactivates(tmp_path):
    emb = HashingEmbedder(DIM)
    store = await _store(tmp_path / "v.db", emb)
    new = Chunk(id="c1", doc_id="doc-c1", source_id="s", url="u", title="T",
                text="Texto totalmente distinto sobre biblioteca central")
    await store.upsert([new], await emb.embed_documents([new.text]))
    assert await store.count() == 3
    res = await _search(store, emb, "biblioteca central", k=1)
    assert res[0].chunk.id == "c1" and res[0].chunk.text.startswith("Texto totalmente")
    old = await _search(store, emb, "quince días semestre", k=3)
    assert all(r.chunk.id != "c1" or r.score < 0.15 for r in old)


async def test_persistence_after_reopen(tmp_path):
    emb = HashingEmbedder(DIM)
    path = tmp_path / "v.db"
    store = await _store(path, emb)
    await store.deactivate_document("doc-c2")
    del store
    reopened = SqliteVectorStore(path, DIM)
    assert await reopened.count() == 2
    res = await _search(reopened, emb, "Secretaría Académica", k=3)
    assert res[0].chunk.id == "c1"
    assert res[0].chunk.metadata == {"facultad": "ING"}


async def test_dimension_change_detected(tmp_path):
    emb = HashingEmbedder(DIM)
    path = tmp_path / "v.db"
    await _store(path, emb)
    with pytest.raises(VectorIndexMismatchError, match="reindexar"):
        SqliteVectorStore(path, DIM * 2)
    store = SqliteVectorStore(path, DIM)
    with pytest.raises(VectorIndexMismatchError, match="reindexar"):
        await store.search(query_text="x", query_vector=[0.0] * 10)


async def test_embedder_change_detected_via_factory(tmp_path):
    emb = HashingEmbedder(DIM)
    s1 = Settings(data_dir=tmp_path, vector_store="sqlite", embedder_provider="hashing",
                  embedder_dimension=DIM, _env_file=None)
    build_vector_store(s1, emb)
    s2 = Settings(data_dir=tmp_path, vector_store="sqlite", embedder_dimension=DIM,
                  embedder_provider="local", _env_file=None)
    with pytest.raises(VectorIndexMismatchError, match="reindexar"):
        build_vector_store(s2, emb)


async def test_factory_memory(tmp_path):
    from unsa_mind.adapters.memory import InMemoryVectorStore

    s = Settings(data_dir=tmp_path, vector_store="memory", _env_file=None)
    assert isinstance(build_vector_store(s, HashingEmbedder(8)), InMemoryVectorStore)
