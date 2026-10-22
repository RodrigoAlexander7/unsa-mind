import json
import math

import httpx
import pytest

from unsa_mind.adapters.embeddings import EmbeddingError, build_embedder
from unsa_mind.adapters.embeddings.gemini import GeminiEmbedder
from unsa_mind.adapters.embeddings.local import LocalEmbedder
from unsa_mind.adapters.embeddings.openai_compat import OpenAICompatEmbedder
from unsa_mind.adapters.memory import HashingEmbedder
from unsa_mind.config.settings import Settings


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


async def test_gemini_batches_and_task_types():
    calls = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        calls.append((req.url.path, req.headers["x-goog-api-key"], body))
        if req.url.path.endswith(":batchEmbedContents"):
            return httpx.Response(
                200, json={"embeddings": [{"values": [3.0, 4.0, 0.0, 0.0]} for _ in body["requests"]]}
            )
        return httpx.Response(200, json={"embedding": {"values": [0.0, 0.0, 3.0, 4.0]}})

    emb = GeminiEmbedder("KEY", dimension=4, client=_client(handler), backoff_s=0)
    vecs = await emb.embed_documents([f"t{i}" for i in range(150)])
    assert len(vecs) == 150 and abs(_norm(vecs[0]) - 1) < 1e-9
    batch_calls = [c for c in calls if c[0].endswith(":batchEmbedContents")]
    assert [len(c[2]["requests"]) for c in batch_calls] == [100, 50]
    assert batch_calls[0][0].endswith("/models/gemini-embedding-001:batchEmbedContents")
    assert batch_calls[0][1] == "KEY"
    r0 = batch_calls[0][2]["requests"][0]
    assert r0["taskType"] == "RETRIEVAL_DOCUMENT" and r0["outputDimensionality"] == 4
    q = await emb.embed_query("hola")
    assert q == [0.0, 0.0, 0.6, 0.8]
    assert calls[-1][2]["taskType"] == "RETRIEVAL_QUERY"


async def test_gemini_requires_key_and_checks_dimension():
    with pytest.raises(EmbeddingError, match="GEMINI_API_KEY"):
        GeminiEmbedder(None)
    client = _client(lambda r: httpx.Response(200, json={"embedding": {"values": [1.0, 2.0]}}))
    emb = GeminiEmbedder("K", dimension=4, client=client)
    with pytest.raises(EmbeddingError, match="dimensión"):
        await emb.embed_query("x")


async def test_retries_then_success_and_failure():
    state = {"n": 0}

    def flaky(req):
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(429 if state["n"] == 1 else 503, text="busy")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    emb = OpenAICompatEmbedder(
        base_url="https://api.example.com/v1", api_key="k", dimension=2,
        client=_client(flaky), backoff_s=0,
    )
    assert await emb.embed_query("x") == [1.0, 0.0]
    assert state["n"] == 3

    bad = OpenAICompatEmbedder(
        base_url="https://api.example.com/v1", api_key="k", dimension=2,
        client=_client(lambda r: httpx.Response(401, text="nope")), backoff_s=0,
    )
    with pytest.raises(EmbeddingError, match="401"):
        await bad.embed_query("x")

    always = OpenAICompatEmbedder(
        base_url="https://api.example.com/v1", api_key="k", dimension=2, retries=2,
        client=_client(lambda r: httpx.Response(500, text="x")), backoff_s=0,
    )
    with pytest.raises(EmbeddingError, match="3 intentos"):
        await always.embed_query("x")


async def test_openai_compat_request_and_order():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        body = json.loads(req.content)
        seen["body"] = body
        data = [{"index": i, "embedding": [float(i + 1), 0.0]} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": list(reversed(data))})  # desordenado a propósito

    emb = OpenAICompatEmbedder(
        base_url="https://openrouter.ai/api/v1/", api_key="sk", model="m", dimension=2,
        send_dimensions=True, client=_client(handler),
    )
    vecs = await emb.embed_documents(["a", "b"])
    assert seen["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert seen["auth"] == "Bearer sk"
    assert seen["body"] == {"model": "m", "input": ["a", "b"], "dimensions": 2}
    assert vecs == [[1.0, 0.0], [1.0, 0.0]]  # normalizados, en el orden de entrada


def test_openai_compat_key_rules():
    with pytest.raises(EmbeddingError, match="EMBEDDER_API_KEY"):
        OpenAICompatEmbedder(base_url="https://api.example.com/v1")
    OpenAICompatEmbedder(base_url="http://localhost:11434/v1")  # Ollama: sin key


async def test_local_embedder_with_injected_model():
    class FakeST:
        def encode(self, texts, normalize_embeddings, show_progress_bar):
            return [[1.0, 0.0, 0.0] for _ in texts]

    emb = LocalEmbedder(dimension=3, st_model=FakeST())
    assert await emb.embed_query("x") == [1.0, 0.0, 0.0]
    assert await emb.embed_documents([]) == []
    wrong = LocalEmbedder(dimension=5, st_model=FakeST())
    with pytest.raises(EmbeddingError, match="dimensión"):
        await wrong.embed_query("x")


def test_factory(tmp_path):
    base = {"data_dir": tmp_path, "_env_file": None}
    h = build_embedder(Settings(embedder_provider="hashing", embedder_dimension=64, **base))
    assert isinstance(h, HashingEmbedder) and h.dimension == 64
    with pytest.raises(EmbeddingError):
        build_embedder(Settings(embedder_provider="gemini", **base))
    g = build_embedder(Settings(embedder_provider="gemini", gemini_api_key="k", **base))
    assert isinstance(g, GeminiEmbedder) and g.model == "gemini-embedding-001"
    o = build_embedder(
        Settings(embedder_provider="openai_compat", embedder_api_key="k", **base)
    )
    assert isinstance(o, OpenAICompatEmbedder)
    loc = build_embedder(Settings(embedder_provider="local", **base))
    assert isinstance(loc, LocalEmbedder) and loc.model_name == "BAAI/bge-m3"
