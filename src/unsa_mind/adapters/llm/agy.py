"""Adaptador que invoca el CLI `agy` (Antigravity) como subproceso, sin API key.

Protocolo NDJSON: se escribe un evento `user` por stdin, se cierra stdin y se leen
eventos de stdout. Los deltas llegan en `step_update` (step_type=agent_response,
campo `text_delta`); el último evento es `result`.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator, Sequence
from typing import Any

from unsa_mind.application.ports import ChatMessage

from .errors import LLMError, TransientLLMError

DEFAULT_MODEL = "claude-sonnet-5-5-medium"
_TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "429", "overloaded")


def build_prompt(messages: Sequence[ChatMessage], system: str | None) -> str:
    """agy no tiene parámetro system ni roles: se aplana todo en un único texto."""
    parts: list[str] = []
    if system:
        parts.append(system.strip())
    if len(messages) == 1:
        parts.append(messages[0].content)
    else:
        for m in messages:
            parts.append(f"{'Usuario' if m.role == 'user' else 'Asistente'}: {m.content}")
    return "\n\n".join(parts)


class AgyLLM:
    name = "agy"

    def __init__(
        self,
        model: str | None = None,
        *,
        agy_bin: str = "agy",
        timeout_s: float = 120.0,
        cwd: str | None = None,
        extra_args: Sequence[str] = (),
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self._bin = shutil.which(agy_bin) or agy_bin
        self._timeout = timeout_s
        self._cwd = cwd
        self._extra = list(extra_args)

    def _args(self) -> list[str]:
        return [
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--model", self.model,
            "--disable-slash-commands",  # el material es texto no confiable
            "--print-timeout", f"{max(1, int(self._timeout))}s",
            *self._extra,
            "-p=",  # forma con valor adjunto: crítica
        ]  # fmt: skip

    async def _events(self, prompt: str) -> AsyncIterator[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._bin,
                *self._args(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
            )
        except OSError as exc:
            raise LLMError(f"agy: no se pudo ejecutar '{self._bin}' ({exc})") from exc
        assert proc.stdin and proc.stdout and proc.stderr
        stderr_task = asyncio.ensure_future(proc.stderr.read())
        msg = {
            "event": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": prompt}]},
        }
        try:
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass  # el proceso murió antes de leer; se informa abajo con su stderr
        got_result = False
        try:
            async with asyncio.timeout(self._timeout + 5):
                async for raw in proc.stdout:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("event") == "result":
                        got_result = True
                    yield event
                await proc.wait()
        except TimeoutError as exc:
            raise TransientLLMError(f"agy: timeout tras {self._timeout}s") from exc
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        if not got_result:
            err = (await stderr_task).decode("utf-8", "replace").strip()[:300]
            raise TransientLLMError(f"agy: sin evento result ({err or 'sin detalle'})")

    @staticmethod
    def _check(result: dict[str, Any]) -> str:
        if result.get("status") != "SUCCESS":
            detail = f"{result.get('status')}: {result.get('error', 'desconocido')}"
            transient = any(c in detail for c in _TRANSIENT_MARKERS)
            raise (TransientLLMError if transient else LLMError)(f"agy: {detail}")
        text = str(result.get("response") or "").strip()
        if not text:
            denied = result.get("denied_actions") or []
            extra = f" (permisos denegados: {denied})" if denied else ""
            raise LLMError(f"agy: respuesta vacía{extra}")
        return text

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        async for event in self._events(build_prompt(messages, system)):
            if event.get("event") == "result":
                return self._check(event.get("result") or {})
        raise LLMError("agy: sin resultado")

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        streamed = False
        async for event in self._events(build_prompt(messages, system)):
            kind = event.get("event")
            if kind == "step_update":
                step = event.get("step_update") or {}
                if step.get("step_type") == "agent_response" and step.get("text_delta"):
                    streamed = True
                    yield step["text_delta"]
            elif kind == "result":
                text = self._check(event.get("result") or {})
                if not streamed:  # sin deltas: se emite la respuesta final por trozos
                    for i in range(0, len(text), 80):
                        yield text[i : i + 80]
