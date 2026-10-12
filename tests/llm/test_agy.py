import json
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from unsa_mind.adapters.llm import AgyLLM, FallbackLLM, TransientLLMError
from unsa_mind.application.ports import ChatMessage
from unsa_mind.domain.errors import LLMError

FAKE = Path(__file__).with_name("fake_agy.py")
MSGS = [ChatMessage("user", "pregunta")]


@pytest.fixture
def fake_bin(tmp_path: Path) -> str:
    """Lanzador ejecutable que delega en fake_agy.py con el intérprete actual."""
    if os.name == "nt":
        path = tmp_path / "agy.cmd"
        path.write_text(f'@echo off\r\n"{sys.executable}" "{FAKE}" %*\r\n')
    else:
        path = tmp_path / "agy"
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


async def collect(it) -> str:
    return "".join([c async for c in it])


async def test_complete_and_protocol(fake_bin, tmp_path, monkeypatch):
    log = tmp_path / "log.json"
    monkeypatch.setenv("FAKE_AGY_LOG", str(log))
    llm = AgyLLM("claude-sonnet-5-5-low", agy_bin=fake_bin, timeout_s=20)
    assert await llm.complete(MSGS, system="SISTEMA") == "hola mundo"
    seen = json.loads(log.read_text(encoding="utf-8"))
    assert seen["text"].startswith("SISTEMA") and seen["text"].endswith("pregunta")
    argv = seen["argv"]
    assert "-p=" in argv and "--dangerously-skip-permissions" not in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5-low"
    assert argv[argv.index("--input-format") + 1] == "stream-json"


async def test_stream_uses_deltas(fake_bin):
    llm = AgyLLM(agy_bin=fake_bin, timeout_s=20)
    chunks = [c async for c in llm.stream(MSGS)]
    assert chunks == ["hola ", "mundo"]


async def test_stream_without_deltas_chunks_final(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "nodeltas")
    assert await collect(AgyLLM(agy_bin=fake_bin, timeout_s=20).stream(MSGS)) == "hola mundo"


async def test_503_is_transient_and_falls_back(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "503")
    with pytest.raises(TransientLLMError):
        await AgyLLM(agy_bin=fake_bin, timeout_s=20).complete(MSGS)


async def test_crash_reports_stderr(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "crash")
    with pytest.raises(LLMError, match="boom"):
        await AgyLLM(agy_bin=fake_bin, timeout_s=20).complete(MSGS)


async def test_missing_binary():
    with pytest.raises(LLMError, match="no se pudo ejecutar"):
        await AgyLLM(agy_bin="no-existe-agy-xyz").complete(MSGS)


async def test_fallback_chain_with_real_adapters(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "503")
    llm = FallbackLLM(
        [AgyLLM("a", agy_bin=fake_bin, timeout_s=20), AgyLLM("b", agy_bin="no-existe-agy-xyz")],
        attempts=2,
        backoff_s=0,
    )
    with pytest.raises(LLMError, match="no se pudo ejecutar"):
        await llm.complete(MSGS)


@pytest.mark.skipif(shutil.which("agy") is None, reason="agy no instalado")
async def test_real_agy():
    llm = AgyLLM("claude-sonnet-5-5-low", timeout_s=90)
    out = await llm.complete([ChatMessage("user", "Responde solo: ok")])
    assert out
