import json

import httpx
import pytest

from unsa_mind.adapters.llm import (
    ClaudeLLM,
    FallbackLLM,
    GeminiLLM,
    OpenRouterLLM,
    TransientLLMError,
    build_llm,
)
from unsa_mind.application.ports import ChatMessage
from unsa_mind.config.settings import Settings
from unsa_mind.domain.errors import LLMError

MSGS = [ChatMessage("user", "hola"), ChatMessage("assistant", "qué tal"), ChatMessage("user", "dime")]


def sse(*events: dict | str) -> bytes:
    return "".join(
        f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events
    ).encode()


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def collect(it) -> str:
    return "".join([c async for c in it])


# ---------- Claude ----------
async def test_claude_complete():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["req"], seen["body"] = req, json.loads(req.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    llm = ClaudeLLM("k", client=client_for(handler))
    assert await llm.complete(MSGS, system="sys", max_tokens=50) == "ok"
    req, body = seen["req"], seen["body"]
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == "k" and req.headers["anthropic-version"] == "2023-06-01"
    assert body["model"] == "claude-sonnet-5-5" and body["system"] == "sys"
    assert body["max_tokens"] == 50
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]


async def test_claude_stream():
    def handler(req: httpx.Request) -> httpx.Response:
        assert json.loads(req.content)["stream"] is True
        delta = lambda t: {  # noqa: E731
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": t},
        }
        return httpx.Response(
            200,
            content=sse({"type": "message_start"}, delta("ho"), delta("la"), {"type": "message_stop"}),
        )

    assert await collect(ClaudeLLM("k", client=client_for(handler)).stream(MSGS)) == "hola"


# ---------- Gemini ----------
async def test_gemini_complete_maps_roles_and_system():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["req"], seen["body"] = req, json.loads(req.content)
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
        )

    llm = GeminiLLM("gk", client=client_for(handler))
    assert await llm.complete(MSGS, system="sys") == "ab"
    req, body = seen["req"], seen["body"]
    assert req.url.path.endswith("/models/gemini-2.5-flash:generateContent")
    assert req.headers["x-goog-api-key"] == "gk" and "key" not in req.url.params
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}


async def test_gemini_stream():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith(":streamGenerateContent")
        assert req.url.params["alt"] == "sse"
        ev = lambda t: {"candidates": [{"content": {"parts": [{"text": t}]}}]}  # noqa: E731
        return httpx.Response(200, content=sse(ev("ho"), ev("la")))

    assert await collect(GeminiLLM("gk", client=client_for(handler)).stream(MSGS)) == "hola"


# ---------- OpenRouter ----------
async def test_openrouter_complete_and_system_message():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["req"], seen["body"] = req, json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    llm = OpenRouterLLM("ok-key", client=client_for(handler))
    assert await llm.complete(MSGS, system="sys") == "ok"
    assert seen["req"].headers["authorization"] == "Bearer ok-key"
    assert seen["body"]["model"] == "anthropic/claude-sonnet-4.5"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}


async def test_openrouter_stream_done():
    def handler(req: httpx.Request) -> httpx.Response:
        ev = lambda t: {"choices": [{"delta": {"content": t}}]}  # noqa: E731
        return httpx.Response(200, content=sse(ev("ho"), {"choices": [{"delta": {}}]}, ev("la"), "[DONE]"))

    assert await collect(OpenRouterLLM("k", client=client_for(handler)).stream(MSGS)) == "hola"


# ---------- Errores ----------
@pytest.mark.parametrize("cls", [ClaudeLLM, GeminiLLM, OpenRouterLLM])
async def test_http_errors(cls):
    def make(status: int):
        return cls("k", client=client_for(lambda r: httpx.Response(status, text="nope")))

    with pytest.raises(LLMError) as e401:
        await make(401).complete(MSGS)
    assert not isinstance(e401.value, TransientLLMError) and "401" in str(e401.value)
    with pytest.raises(TransientLLMError):
        await make(429).complete(MSGS)
    with pytest.raises(TransientLLMError):
        await collect(make(503).stream(MSGS))


@pytest.mark.parametrize("cls", [ClaudeLLM, GeminiLLM, OpenRouterLLM])
def test_missing_key(cls):
    with pytest.raises(LLMError):
        cls("")


# ---------- Fallback / factory ----------
class Flaky:
    name = "flaky"

    def __init__(self, fails: list[LLMError], reply: str = "ok") -> None:
        self.fails, self.reply, self.calls = fails, reply, 0

    async def complete(self, messages, **kw) -> str:
        self.calls += 1
        if self.fails:
            raise self.fails.pop(0)
        return self.reply

    async def stream(self, messages, **kw):
        self.calls += 1
        if self.fails:
            raise self.fails.pop(0)
        yield self.reply


async def test_fallback_retries_then_next_model():
    a = Flaky([TransientLLMError("503")] * 5)
    b = Flaky([], "de b")
    llm = FallbackLLM([a, b], attempts=2, backoff_s=0)
    assert await llm.complete(MSGS) == "de b"
    assert a.calls == 2 and b.calls == 1
    assert await collect(llm.stream(MSGS)) == "de b"


async def test_fallback_permanent_error_skips_retries():
    a = Flaky([LLMError("401")] * 3)
    b = Flaky([], "b")
    assert await FallbackLLM([a, b], attempts=3, backoff_s=0).complete(MSGS) == "b"
    assert a.calls == 1


async def test_fallback_all_fail():
    llm = FallbackLLM([Flaky([TransientLLMError("x")] * 2)], attempts=2, backoff_s=0)
    with pytest.raises(LLMError):
        await llm.complete(MSGS)


def test_factory():
    assert build_llm(Settings(llm_provider="fake", _env_file=None)).name == "fake"
    with pytest.raises(LLMError, match="API key"):
        build_llm(Settings(llm_provider="claude", anthropic_api_key=None, _env_file=None))
    s = Settings(llm_provider="gemini", gemini_api_key="k", llm_model="m1", _env_file=None)
    assert build_llm(s).name == "gemini"
    s = Settings(
        llm_provider="openrouter", openrouter_api_key="k", llm_fallback_models=["m2"], _env_file=None
    )
    assert isinstance(build_llm(s), FallbackLLM)
    assert build_llm(Settings(llm_provider="agy", _env_file=None)).name == "agy"
