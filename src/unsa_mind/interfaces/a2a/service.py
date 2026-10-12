"""Lógica del protocolo A2A (Agent2Agent 0.3), independiente de FastAPI.

El servicio recibe `params` ya decodificados del JSON-RPC y devuelve/emite `result`s;
el router se encarga del sobre JSON-RPC (`jsonrpc`, `id`, `error`) y del transporte SSE.

Decisión de diseño: `message/send` responde con un `Message` directo (la consulta es corta y
sin estado largo). Solo si el cliente aporta `taskId` se devuelve un `Task` completado con
su artefacto. `message/stream` siempre crea un `Task` (consultable con `tasks/get`).
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from unsa_mind.application.ports import ChatMessage
from unsa_mind.application.use_cases.ask_question import AskQuestion
from unsa_mind.config.settings import Settings
from unsa_mind.interfaces.common import answer_payload

PROTOCOL_VERSION = "0.3.0"

# Códigos JSON-RPC estándar y de A2A
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002

TERMINAL_STATES = {"completed", "canceled", "failed", "rejected"}

SKILLS: list[dict[str, Any]] = [
    {
        "id": "admision",
        "name": "Admisión",
        "description": "Información sobre procesos de admisión, vacantes, cronogramas y requisitos.",
        "tags": ["admision", "ingreso", "postulacion"],
        "examples": ["¿Cuáles son los requisitos para postular a la UNSA?"],
    },
    {
        "id": "posgrado",
        "name": "Posgrado",
        "description": "Maestrías, doctorados, requisitos de matrícula y calendario de la Escuela de Posgrado.",
        "tags": ["posgrado", "maestria", "doctorado"],
        "examples": ["¿Qué maestrías ofrece la Escuela de Posgrado?"],
    },
    {
        "id": "convenios",
        "name": "Convenios",
        "description": "Convenios institucionales nacionales e internacionales y movilidad.",
        "tags": ["convenios", "movilidad", "cooperacion"],
        "examples": ["¿Con qué universidades tiene convenio la UNSA?"],
    },
    {
        "id": "tramites",
        "name": "Trámites",
        "description": "Trámites académicos y administrativos: reserva de matrícula, constancias, reglamentos.",
        "tags": ["tramites", "matricula", "constancias"],
        "examples": ["¿Cómo solicito la reserva de matrícula?"],
    },
]


class A2AError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _TTLStore:
    """Diccionario en memoria con expiración y tamaño máximo (LRU)."""

    def __init__(self, ttl_s: float, max_items: int) -> None:
        self._ttl = ttl_s
        self._max = max_items
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def _purge(self) -> None:
        now = time.monotonic()
        for k in [k for k, (exp, _) in self._items.items() if exp <= now]:
            del self._items[k]
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def get(self, key: str) -> Any | None:
        self._purge()
        item = self._items.get(key)
        if item is None:
            return None
        self._items[key] = (time.monotonic() + self._ttl, item[1])  # renueva TTL
        self._items.move_to_end(key)
        return item[1]

    def put(self, key: str, value: Any) -> None:
        self._items[key] = (time.monotonic() + self._ttl, value)
        self._items.move_to_end(key)
        self._purge()


class A2AService:
    def __init__(
        self,
        ask: AskQuestion,
        settings: Settings,
        *,
        task_ttl_s: float = 3600.0,
        max_tasks: int = 1000,
        max_contexts: int = 500,
        max_history: int = 12,
    ) -> None:
        self._ask = ask
        self._settings = settings
        self._tasks = _TTLStore(task_ttl_s, max_tasks)
        self._contexts = _TTLStore(task_ttl_s, max_contexts)
        self._max_history = max_history

    # ---- Agent Card -------------------------------------------------------------------
    def agent_card(self) -> dict[str, Any]:
        s = self._settings
        card: dict[str, Any] = {
            "name": "Asistente Virtual UNSA",
            "description": (
                "Asistente institucional de la Universidad Nacional de San Agustín de Arequipa. "
                "Responde con citas a fuentes oficiales sobre admisión, posgrado, convenios y trámites."
            ),
            "url": s.public_url.rstrip("/") + "/a2a",
            "preferredTransport": "JSONRPC",
            "version": "0.1.0",
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"streaming": True, "pushNotifications": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": SKILLS,
        }
        if s.admin_token:  # solo aplica a la administración REST; el chat A2A es público
            card["securitySchemes"] = {"adminBearer": {"type": "http", "scheme": "bearer"}}
        return card

    # ---- Despacho ---------------------------------------------------------------------
    async def call(self, method: str, params: Any) -> dict[str, Any]:
        """Métodos no streaming. Devuelve el `result`."""
        if method == "message/send":
            return await self._send(params)
        if method == "tasks/get":
            return self._get_task(params)
        if method == "tasks/cancel":
            return self._cancel_task(params)
        raise A2AError(METHOD_NOT_FOUND, f"Método no soportado: {method}")

    @staticmethod
    def is_streaming(method: str) -> bool:
        return method == "message/stream"

    # ---- Parseo -----------------------------------------------------------------------
    @staticmethod
    def _parse_message(params: Any) -> tuple[str, str, str | None]:
        if not isinstance(params, dict) or not isinstance(params.get("message"), dict):
            raise A2AError(INVALID_PARAMS, "params.message es obligatorio")
        msg = params["message"]
        parts = msg.get("parts")
        if not isinstance(parts, list) or not parts:
            raise A2AError(INVALID_PARAMS, "message.parts debe ser una lista no vacía")
        texts = [
            p["text"]
            for p in parts
            if isinstance(p, dict)
            and (p.get("kind") or p.get("type")) == "text"
            and isinstance(p.get("text"), str)
        ]
        text = "\n".join(texts).strip()
        if not text:
            raise A2AError(INVALID_PARAMS, "se requiere al menos una parte de texto no vacía")
        if len(text) > 2000:
            raise A2AError(INVALID_PARAMS, "el texto excede 2000 caracteres")
        if msg.get("role", "user") != "user":
            raise A2AError(INVALID_PARAMS, "message.role debe ser 'user'")
        context_id = msg.get("contextId") or str(uuid.uuid4())
        task_id = msg.get("taskId")
        if not isinstance(context_id, str) or (task_id is not None and not isinstance(task_id, str)):
            raise A2AError(INVALID_PARAMS, "contextId y taskId deben ser cadenas")
        return text, context_id, task_id

    def _history(self, context_id: str) -> list[ChatMessage]:
        hist: deque[ChatMessage] | None = self._contexts.get(context_id)
        return list(hist) if hist else []

    def _remember(self, context_id: str, question: str, answer: str) -> None:
        hist: deque[ChatMessage] | None = self._contexts.get(context_id)
        if hist is None:
            hist = deque(maxlen=self._max_history)
        hist.append(ChatMessage("user", question))
        hist.append(ChatMessage("assistant", answer))
        self._contexts.put(context_id, hist)

    # ---- Construcción de objetos A2A --------------------------------------------------
    @staticmethod
    def _agent_message(text: str, context_id: str, task_id: str | None, meta: dict) -> dict:
        msg = {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid.uuid4()),
            "contextId": context_id,
            "parts": [{"kind": "text", "text": text}],
            "metadata": meta,
        }
        if task_id:
            msg["taskId"] = task_id
        return msg

    @staticmethod
    def _meta(payload: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in payload.items() if k != "answer"}

    def _new_task(self, task_id: str, context_id: str, question: str) -> dict[str, Any]:
        task = {
            "kind": "task",
            "id": task_id,
            "contextId": context_id,
            "status": {"state": "working", "timestamp": _now()},
            "artifacts": [],
            "history": [
                {
                    "kind": "message",
                    "role": "user",
                    "messageId": str(uuid.uuid4()),
                    "taskId": task_id,
                    "contextId": context_id,
                    "parts": [{"kind": "text", "text": question}],
                }
            ],
        }
        self._tasks.put(task_id, task)
        return task

    def _complete(self, task: dict, payload: dict[str, Any]) -> None:
        if task["status"]["state"] == "canceled":
            return
        task["artifacts"] = [
            {
                "artifactId": f"{task['id']}-answer",
                "name": "respuesta",
                "parts": [{"kind": "text", "text": payload["answer"]}],
                "metadata": self._meta(payload),
            }
        ]
        task["status"] = {"state": "completed", "timestamp": _now()}

    def _claim_task_id(self, task_id: str | None) -> str:
        if task_id is None:
            return str(uuid.uuid4())
        existing = self._tasks.get(task_id)
        if existing and existing["status"]["state"] in TERMINAL_STATES:
            raise A2AError(INVALID_PARAMS, f"La tarea {task_id} ya finalizó; usa otro taskId")
        return task_id

    # ---- message/send -----------------------------------------------------------------
    async def _send(self, params: Any) -> dict[str, Any]:
        text, context_id, req_task_id = self._parse_message(params)
        task_id = self._claim_task_id(req_task_id)
        answer = await self._ask.execute(text, history=self._history(context_id))
        payload = answer_payload(answer)
        self._remember(context_id, text, answer.text)
        if req_task_id is None:
            return self._agent_message(answer.text, context_id, None, self._meta(payload))
        task = self._new_task(task_id, context_id, text)
        self._complete(task, payload)
        return task

    # ---- message/stream ---------------------------------------------------------------
    def stream(self, params: Any) -> AsyncIterator[dict[str, Any]]:
        """Valida de inmediato (para poder responder error JSON-RPC) y devuelve el iterador."""
        text, context_id, req_task_id = self._parse_message(params)  # errores antes de abrir SSE
        task_id = self._claim_task_id(req_task_id)
        return self._stream(text, context_id, task_id)

    async def _stream(self, text: str, context_id: str, task_id: str) -> AsyncIterator[dict[str, Any]]:
        task = self._new_task(task_id, context_id, text)
        artifact_id = f"{task_id}-answer"

        def status(state: str, final: bool, meta: dict | None = None, msg: str | None = None) -> dict:
            st: dict[str, Any] = {"state": state, "timestamp": _now()}
            if msg:
                st["message"] = self._agent_message(msg, context_id, task_id, {})
            ev: dict[str, Any] = {
                "kind": "status-update",
                "taskId": task_id,
                "contextId": context_id,
                "status": st,
                "final": final,
            }
            if meta:
                ev["metadata"] = meta
            return ev

        def chunk(token: str, first: bool, last: bool, meta: dict | None = None) -> dict:
            art: dict[str, Any] = {"artifactId": artifact_id, "name": "respuesta",
                                   "parts": [{"kind": "text", "text": token}]}
            if meta:
                art["metadata"] = meta
            return {
                "kind": "artifact-update",
                "taskId": task_id,
                "contextId": context_id,
                "artifact": art,
                "append": not first,
                "lastChunk": last,
            }

        yield status("working", False)
        held: str | None = None  # se retiene un token para marcar el último con lastChunk
        first = True
        try:
            async for ev in self._ask.stream(text, history=self._history(context_id)):
                if task["status"]["state"] == "canceled":
                    yield status("canceled", True)
                    return
                if ev.kind == "token":
                    if held is not None:
                        yield chunk(held, first, False)
                        first = False
                    held = ev.token
                elif ev.kind == "final" and ev.answer is not None:
                    payload = answer_payload(ev.answer)
                    if held is None:
                        held = ev.answer.text
                    yield chunk(held, first, True, self._meta(payload))
                    self._remember(context_id, text, ev.answer.text)
                    self._complete(task, payload)
                    yield status("completed", True, self._meta(payload))
                    return
            if task["status"]["state"] != "canceled":  # el LLM terminó sin evento final
                task["status"] = {"state": "failed", "timestamp": _now()}
                yield status("failed", True, msg="La respuesta terminó sin resultado")
        except Exception as exc:
            task["status"] = {"state": "failed", "timestamp": _now()}
            yield status("failed", True, msg=f"No se pudo generar la respuesta: {exc}")

    # ---- tasks/get, tasks/cancel ------------------------------------------------------
    def _lookup(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict) or not isinstance(params.get("id"), str):
            raise A2AError(INVALID_PARAMS, "params.id es obligatorio")
        task = self._tasks.get(params["id"])
        if task is None:
            raise A2AError(TASK_NOT_FOUND, f"Tarea no encontrada: {params['id']}")
        return task

    def _get_task(self, params: Any) -> dict[str, Any]:
        task = self._lookup(params)
        n = params.get("historyLength")
        if isinstance(n, int) and n >= 0:
            task = {**task, "history": task["history"][-n:] if n else []}
        return task

    def _cancel_task(self, params: Any) -> dict[str, Any]:
        task = self._lookup(params)
        if task["status"]["state"] in TERMINAL_STATES:
            raise A2AError(TASK_NOT_CANCELABLE, "La tarea ya finalizó y no puede cancelarse")
        task["status"] = {"state": "canceled", "timestamp": _now()}
        return task
