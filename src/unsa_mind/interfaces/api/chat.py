"""Chat: SSE (`/api/chat`), JSON (`/api/chat/sync`) y feedback."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from unsa_mind.application.ports import ChatMessage
from unsa_mind.config.container import Container
from unsa_mind.interfaces.api.deps import get_container, rate_limit_chat
from unsa_mind.interfaces.api.schemas import ChatRequest, ChatResponse, FeedbackRequest
from unsa_mind.interfaces.common import answer_payload

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _history(req: ChatRequest) -> list[ChatMessage]:
    return [ChatMessage(h.role, h.content) for h in req.history]


@router.post("/chat", dependencies=[Depends(rate_limit_chat)])
async def chat(req: ChatRequest, c: Container = Depends(get_container)) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        try:
            async for ev in c.ask.stream(req.message, history=_history(req), filters=req.filters):
                if ev.kind == "token":
                    yield sse("token", {"text": ev.token})
                elif ev.kind == "final" and ev.answer is not None:
                    yield sse("final", answer_payload(ev.answer))
        except Exception as exc:  # el cliente SSE ya recibió 200: se informa por evento
            log.exception("Error en /api/chat")
            yield sse("error", {"message": f"No se pudo generar la respuesta: {exc}"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/sync", response_model=ChatResponse, dependencies=[Depends(rate_limit_chat)])
async def chat_sync(req: ChatRequest, c: Container = Depends(get_container)) -> ChatResponse:
    answer = await c.ask.execute(req.message, history=_history(req), filters=req.filters)
    return ChatResponse(**answer_payload(answer))


def _append(path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


@router.post("/feedback", status_code=202)
async def feedback(fb: FeedbackRequest, c: Container = Depends(get_container)) -> JSONResponse:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "message_id": fb.message_id,
        "value": fb.value,
        "comment": fb.comment,
    }
    await asyncio.to_thread(
        _append, c.settings.data_dir / "feedback.jsonl", json.dumps(record, ensure_ascii=False)
    )
    log.info("feedback value=%s message_id=%s", fb.value, fb.message_id)
    return JSONResponse({"status": "accepted"}, status_code=202)
