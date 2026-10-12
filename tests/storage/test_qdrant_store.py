import pytest

pytest.importorskip("qdrant_client")

from unsa_mind.adapters.memory import HashingEmbedder  # noqa: E402
from unsa_mind.adapters.vectorstore.qdrant_store import QdrantVectorStore, point_id  # noqa: E402
from unsa_mind.domain.entities import Chunk  # noqa: E402


def test_point_id_is_deterministic_uuid():
    assert point_id("abc") == point_id("abc") != point_id("abd")


async def test_qdrant_in_memory_roundtrip():
    emb = HashingEmbedder(128)
    store = QdrantVectorStore(128, url=":memory:", collection="t")
    chunks = [
        Chunk("c1", "d1", "s", "u1", "T", "reserva de matrícula en secretaría", metadata={"f": "A"}),
        Chunk("c2", "d2", "s", "u2", "T", "examen de admisión ordinario", metadata={"f": "B"}),
    ]
    await store.upsert(chunks, await emb.embed_documents([c.indexable_text for c in chunks]))
    q = "reserva de matrícula"
    res = await store.search(query_text=q, query_vector=await emb.embed_query(q), k=2)
    assert res[0].chunk.id == "c1" and 0 <= res[0].score <= 1
    res = await store.search(
        query_text=q, query_vector=await emb.embed_query(q), filters={"f": "B"}
    )
    assert [r.chunk.id for r in res] == ["c2"]
    assert await store.deactivate_document("d1") == 1
    assert await store.count() == 1
    res = await store.search(query_text=q, query_vector=await emb.embed_query(q))
    assert [r.chunk.id for r in res] == ["c2"]
