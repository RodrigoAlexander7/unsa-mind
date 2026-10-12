from __future__ import annotations

import importlib.util

import pytest

from unsa_mind.adapters.scraping.scrapling_fetcher import ScraplingFetcher
from unsa_mind.config.settings import Settings
from unsa_mind.domain.errors import FetchError

HAS_SCRAPLING = importlib.util.find_spec("scrapling") is not None


class _Page:
    status = 200
    url = "https://ejemplo.edu/p"
    headers = {"Content-Type": "text/html; charset=utf-8"}
    body = b'<a href="/q#z">q</a><a href="https://x.com/">x</a>'


class _FakeFetcher:
    @staticmethod
    def get(url, headers=None):
        return _Page()


class _FakeModule:
    Fetcher = _FakeFetcher
    StealthyFetcher = _FakeFetcher


async def test_with_injected_module():
    f = ScraplingFetcher(Settings(), module=_FakeModule)
    raw = await f.fetch("https://ejemplo.edu/p", source_id="s")
    assert raw.content_type == "text/html"
    assert raw.links == ("https://ejemplo.edu/q",)


async def test_error_wrapped():
    class Boom:
        @staticmethod
        def get(url, headers=None):
            raise RuntimeError("x")

    class Mod:
        Fetcher = Boom
        StealthyFetcher = Boom

    with pytest.raises(FetchError):
        await ScraplingFetcher(Settings(), module=Mod).fetch("https://a.edu/", source_id="s")


@pytest.mark.skipif(HAS_SCRAPLING, reason="scrapling instalado")
def test_clear_error_when_not_installed():
    with pytest.raises(RuntimeError, match="scrapling"):
        ScraplingFetcher(Settings())


@pytest.mark.skipif(not HAS_SCRAPLING, reason="requiere el extra opcional scrapling")
def test_constructs_with_real_scrapling():
    ScraplingFetcher(Settings())
