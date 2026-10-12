import json

import httpx
import pytest

from unsa_mind.interfaces.api.app import create_app

Q = "¿Cómo solicito la reserva de matrícula?"


@pytest.fixture
async def client(container):
    app = create_app(container)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as cl:
        yield cl


def rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}


def msg(text, **extra):
    return {"message": {"role": "user", "messageId": "m", "parts": [{"kind": "text", "text": text}], **extra}}


def events(text):
    return [json.loads(b[6:]) for b in text.strip().split("\n\n")]


async def test_agent_card(client, container):
    for path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
        card = (await client.get(path)).json()
        assert card["name"] == "Asistente Virtual UNSA"
        assert card["url"] == container.settings.public_url + "/a2a"
        assert card["protocolVersion"] == "0.3.0"
        assert card["capabilities"] == {"streaming": True, "pushNotifications": False}
        assert [s["id"] for s in card["skills"]] == ["admision", "posgrado", "convenios", "tramites"]
        assert card["defaultInputModes"] == ["text/plain"] and "securitySchemes" not in card


async def test_message_send_returns_message_with_citations(client):
    r = (await client.post("/a2a", json=rpc("message/send", msg(Q)))).json()
    res = r["result"]
    assert r["id"] == 1 and res["kind"] == "message" and res["role"] == "agent"
    assert res["parts"][0]["kind"] == "text" and "[1]" in res["parts"][0]["text"]
    assert res["metadata"]["citations"][0]["url"] == "https://unsa.test/reg"
    assert res["contextId"]


async def test_message_send_abstains(client):
    res = (await client.post("/a2a", json=rpc("message/send", msg("dame una receta de pastel")))).json()["result"]
    assert res["metadata"]["abstained"] is True


async def test_message_send_with_task_id_returns_task(client):
    res = (await client.post("/a2a", json=rpc("message/send", msg(Q, taskId="t1", contextId="c1")))).json()["result"]
    assert res["kind"] == "task" and res["id"] == "t1" and res["status"]["state"] == "completed"
    assert res["artifacts"][0]["parts"][0]["text"]
    got = (await client.post("/a2a", json=rpc("tasks/get", {"id": "t1"}))).json()["result"]
    assert got["id"] == "t1"
    r = (await client.post("/a2a", json=rpc("tasks/cancel", {"id": "t1"}))).json()
    assert r["error"]["code"] == -32002


async def test_context_history_is_kept(client, container, monkeypatch):
    seen = []
    orig = container.ask.execute

    async def spy(q, *, history=(), filters=None):
        seen.append(list(history))
        return await orig(q, history=history, filters=filters)

    monkeypatch.setattr(container.ask, "execute", spy)
    await client.post("/a2a", json=rpc("message/send", msg(Q, contextId="ctx")))
    await client.post("/a2a", json=rpc("message/send", msg(Q, contextId="ctx")))
    assert seen[0] == [] and [m.role for m in seen[1]] == ["user", "assistant"]


async def test_message_stream(client):
    r = await client.post("/a2a", json=rpc("message/stream", msg(Q)))
    assert r.headers["content-type"].startswith("text/event-stream")
    evs = [e["result"] for e in events(r.text)]
    kinds = [e["kind"] for e in evs]
    assert kinds[0] == "status-update" and evs[0]["status"]["state"] == "working" and not evs[0]["final"]
    assert kinds[-1] == "status-update" and evs[-1]["final"] and evs[-1]["status"]["state"] == "completed"
    arts = [e for e in evs if e["kind"] == "artifact-update"]
    assert len(arts) > 1 and arts[0]["append"] is False and arts[-1]["lastChunk"] is True
    assert all(a["append"] for a in arts[1:])
    assert evs[-1]["metadata"]["citations"]
    task_id = evs[0]["taskId"]
    task = (await client.post("/a2a", json=rpc("tasks/get", {"id": task_id}))).json()["result"]
    assert task["status"]["state"] == "completed"
    assert "".join(a["artifact"]["parts"][0]["text"] for a in arts).strip() == task["artifacts"][0]["parts"][0]["text"]


async def test_stream_invalid_params_is_plain_jsonrpc_error(client):
    r = (await client.post("/a2a", json=rpc("message/stream", {"message": {"parts": []}}))).json()
    assert r["error"]["code"] == -32602


async def test_task_not_found(client):
    for m in ("tasks/get", "tasks/cancel"):
        r = (await client.post("/a2a", json=rpc(m, {"id": "nope"}))).json()
        assert r["error"]["code"] == -32001


async def test_jsonrpc_errors(client):
    r = (await client.post("/a2a", content="{no json", headers={"content-type": "application/json"})).json()
    assert r["error"]["code"] == -32700 and r["id"] is None
    assert (await client.post("/a2a", json=[1, 2])).json()["error"]["code"] == -32600
    assert (await client.post("/a2a", json={"jsonrpc": "1.0", "id": 1, "method": "x"})).json()["error"]["code"] == -32600
    r = (await client.post("/a2a", json=rpc("foo/bar"))).json()
    assert r["error"]["code"] == -32601 and r["id"] == 1
    assert (await client.post("/a2a", json=rpc("message/send", {"message": "hola"}))).json()["error"]["code"] == -32602
    assert (await client.post("/a2a", json=rpc("message/send", msg("   ")))).json()["error"]["code"] == -32602
    assert (await client.post("/a2a", json=rpc("tasks/get", None))).json()["error"]["code"] == -32602


async def test_internal_error(client, container, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(container.ask, "execute", boom)
    assert (await client.post("/a2a", json=rpc("message/send", msg(Q)))).json()["error"]["code"] == -32603
