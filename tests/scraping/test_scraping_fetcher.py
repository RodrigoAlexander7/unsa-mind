from __future__ import annotations

import httpx
import pytest

from unsa_mind.adapters.scraping.factory import build_fetcher, build_parsers
from unsa_mind.adapters.scraping.httpx_fetcher import HttpxFetcher
from unsa_mind.config.settings import Settings
from unsa_mind.domain.errors import FetchError

HTML = b"""<html><body>
<a href="/a#frag">A</a><a href="/a">A2</a><a href="https://ejemplo.edu/b?x=1">B</a>
<a href="https://otro.com/x">ext</a><a href="mailto:x@y.z">m</a><a href="rel/c">C</a>
</body></html>"""


def make(handler, **kw):
    settings = Settings(request_delay_s=kw.pop("delay", 0.0), respect_robots=kw.pop("robots", False))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    return HttpxFetcher(settings, client, sleep=fake_sleep, **kw), sleeps


async def test_fetch_html_links_same_domain_normalized():
    def h(req):
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=HTML)

    f, _ = make(h)
    raw = await f.fetch("https://ejemplo.edu/dir/", source_id="s1")
    assert raw.content_type == "text/html"
    assert raw.source_id == "s1"
    assert raw.links == (
        "https://ejemplo.edu/a",
        "https://ejemplo.edu/b?x=1",
        "https://ejemplo.edu/dir/rel/c",
    )


async def test_pdf_has_no_links_and_user_agent_sent():
    seen = {}

    def h(req):
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4")

    f, _ = make(h)
    raw = await f.fetch("https://ejemplo.edu/x.pdf", source_id="s")
    assert raw.content_type == "application/pdf" and raw.links == ()
    assert seen["ua"] == Settings().user_agent


async def test_retries_with_backoff_then_succeeds():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503 if calls["n"] == 1 else 429)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>ok</p>")

    f, sleeps = make(h, backoff_s=1.0)
    raw = await f.fetch("https://ejemplo.edu/", source_id="s")
    assert calls["n"] == 3 and raw.body == b"<p>ok</p>"
    assert sleeps == [1.0, 2.0]


async def test_retries_exhausted_raises_fetch_error():
    f, _ = make(lambda req: httpx.Response(500), max_retries=2)
    with pytest.raises(FetchError):
        await f.fetch("https://ejemplo.edu/", source_id="s")


async def test_404_no_retry():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(404)

    f, _ = make(h)
    with pytest.raises(FetchError, match="404"):
        await f.fetch("https://ejemplo.edu/nada", source_id="s")
    assert calls["n"] == 1


async def test_size_limit():
    f, _ = make(lambda req: httpx.Response(200, content=b"x" * 5000), max_bytes=1000)
    with pytest.raises(FetchError, match="tamaño"):
        await f.fetch("https://ejemplo.edu/big", source_id="s")


async def test_transport_error_becomes_fetch_error():
    def h(req):
        raise httpx.ConnectError("boom")

    f, _ = make(h, max_retries=1)
    with pytest.raises(FetchError):
        await f.fetch("https://ejemplo.edu/", source_id="s")


async def test_follows_redirects():
    def h(req):
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>x</p>")

    f, _ = make(h)
    raw = await f.fetch("https://ejemplo.edu/old", source_id="s")
    assert raw.url == "https://ejemplo.edu/new"


async def test_robots_disallow_and_cache():
    hits = {"robots": 0}

    def h(req):
        if req.url.path == "/robots.txt":
            hits["robots"] += 1
            return httpx.Response(200, text="User-agent: *\nDisallow: /privado\n")
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>x</p>")

    f, _ = make(h, robots=True)
    await f.fetch("https://ejemplo.edu/publico", source_id="s")
    await f.fetch("https://ejemplo.edu/otro", source_id="s")
    with pytest.raises(FetchError, match="robots"):
        await f.fetch("https://ejemplo.edu/privado/x", source_id="s")
    assert hits["robots"] == 1


async def test_robots_missing_allows():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>x</p>")

    f, _ = make(h, robots=True)
    assert (await f.fetch("https://ejemplo.edu/a", source_id="s")).body == b"<p>x</p>"


async def test_polite_delay_per_domain():
    def h(req):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>x</p>")

    f, sleeps = make(h, delay=5.0)
    await f.fetch("https://a.edu/1", source_id="s")
    await f.fetch("https://b.edu/1", source_id="s")  # otro dominio: sin espera
    assert sleeps == []
    await f.fetch("https://a.edu/2", source_id="s")  # mismo dominio: espera
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 5.0


def test_factory_builds():
    assert isinstance(build_fetcher(Settings(fetcher="httpx")), HttpxFetcher)
    parsers = build_parsers(Settings())
    assert any(p.supports("text/html") for p in parsers)
    assert any(p.supports("application/pdf") for p in parsers)
