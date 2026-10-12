"""Transporte JSON-RPC 2.0 de A2A sobre HTTP (+ SSE para `message/stream`).

Ejemplos (servidor en http://localhost:8000):

    curl http://localhost:8000/.well-known/agent-card.json

    curl -X POST http://localhost:8000/a2a -H 'Content-Type: application/json' -d '{
      "jsonrpc": "2.0", "id": 1, "method": "message/send",
      "params": {"message": {"role": "user", "messageId": "m1",
                 "parts": [{"kind": "text", "text": "¿Cómo solicito la reserva de matrícula?"}]}}}'

    curl -N -X POST http://localhost:8000/a2a -H 'Content-Type: application/json' -d '{
      "jsonrpc": "2.0", "id": 2, "method": "message/stream",
      "params": {"message": {"role": "user", "messageId": "m2",
                 "parts": [{"kind": "text", "text": "Requisitos de admisión"}]}}}'

    curl -X POST http://localhost:8000/a2a -H 'Content-Type: application/json' -d '{
      "jsonrpc": "2.0", "id": 3, "method": "tasks/get", "params": {"id": "<task-id>"}}'
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from unsa_mind.interfaces.a2a.service import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    PARSE_ERROR,
    A2AError,
    A2AService,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["a2a"])


def _ok(rid: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": error}


def _service(request: Request) -> A2AService:
    return request.app.state.a2a


@router.get("/.well-known/agent-card.json")
@router.get("/.well-known/agent.json")
async def agent_card(request: Request) -> JSONResponse:
    return JSONResponse(_service(request).agent_card())


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/a2a")
async def a2a_rpc(request: Request):
    service = _service(request)
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(_err(None, PARSE_ERROR, "JSON inválido"))
    if (
        not isinstance(body, dict)
        or body.get("jsonrpc") != "2.0"
        or not isinstance(body.get("method"), str)
        or isinstance(body.get("id"), (dict, list, bool))
    ):
        rid = body.get("id") if isinstance(body, dict) and isinstance(body.get("id"), (str, int)) else None
        return JSONResponse(_err(rid, INVALID_REQUEST, "Solicitud JSON-RPC inválida"))

    rid, method, params = body.get("id"), body["method"], body.get("params")
    try:
        if service.is_streaming(method):
            events = service.stream(params)  # valida antes de abrir el stream
            return StreamingResponse(
                _stream(rid, events),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(_ok(rid, await service.call(method, params)))
    except A2AError as exc:
        return JSONResponse(_err(rid, exc.code, exc.message, exc.data))
    except Exception:
        log.exception("Error interno en A2A (%s)", method)
        return JSONResponse(_err(rid, INTERNAL_ERROR, "Error interno"))


async def _stream(rid: Any, events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    try:
        async for ev in events:
            yield _sse(_ok(rid, ev))
    except Exception:
        log.exception("Error interno en A2A stream")
        yield _sse(_err(rid, INTERNAL_ERROR, "Error interno"))
