import json

import httpx
import pytest

from unsa_mind.interfaces.api.app import create_app

from .conftest import make_container, parse_sse

Q = "¿Cómo solicito la reserva de matrícula?"


@pytest.fixture
async def client(container):
    app = create_app(container)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as cl:
            yield cl


async def test_lifespan_starts_and_stops_scheduler(container):
    app = create_app(container)
    async with app.router.lifespan_context(app):
        assert container.scheduler.started_with.interval_minutes == 60
        assert container.scheduler.job is not None
    assert container.scheduler.stopped


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["llm"] == "fake" and body["vector_chunks"] >= 1
    assert body["next_update"]


async def test_chat_sse_sequence(client):
    r = await client.post("/api/chat", json={"message": Q})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    events = parse_sse(r.text)
    names = [e for e, _ in events]
    assert names[-1] == "final" and set(names[:-1]) == {"token"} and len(names) > 2
    final = events[-1][1]
    assert set(final) == {"answer", "citations", "abstained", "intent", "data_as_of"}
    assert final["abstained"] is False and final["citations"][0]["url"] == "https://unsa.test/reg"
    assert set(final["citations"][0]) == {"title", "section", "url", "updated_at"}
    assert "".join(d["text"] for e, d in events if e == "token").strip() == final["answer"]


async def test_chat_sync_and_abstention(client):
    ok = (await client.post("/api/chat/sync", json={"message": Q, "history": [
        {"role": "user", "content": "hola"}, {"role": "assistant", "content": "¡Hola!"}]})).json()
    assert ok["citations"] and not ok["abstained"] and ok["data_as_of"]
    no = (await client.post("/api/chat/sync", json={"message": "dame una receta de pastel"})).json()
    assert no["abstained"] is True and no["citations"] == []


async def test_chat_stream_error_event(container, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("fallo")
        yield

    monkeypatch.setattr(container.ask, "stream", boom)
    app = create_app(container)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as cl:
        events = parse_sse((await cl.post("/api/chat", json={"message": Q})).text)
    assert events[-1][0] == "error" and "fallo" in events[-1][1]["message"]


async def test_chat_validation(client):
    assert (await client.post("/api/chat/sync", json={"message": ""})).status_code == 422
    assert (await client.post("/api/chat/sync", json={"message": "x" * 2001})).status_code == 422
    assert (await client.post("/api/chat/sync", json={"message": "a", "history": [
        {"role": "system", "content": "x"}]})).status_code == 422


async def test_rate_limit(container):
    app = create_app(container, rate_limit_per_minute=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as cl:
        codes = [(await cl.post("/api/chat/sync", json={"message": Q})).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


async def test_feedback_writes_jsonl(client, container):
    r = await client.post("/api/feedback", json={"message_id": "m1", "value": "up", "comment": "ok"})
    assert r.status_code == 202
    line = (container.settings.data_dir / "feedback.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["value"] == "up"
    assert (await client.post("/api/feedback", json={"value": "meh"})).status_code == 422


async def test_cors_header(client):
    r = await client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


# ---- admin ------------------------------------------------------------------------------
@pytest.fixture
def secured_container(tmp_path):
    return make_container(tmp_path, admin_token="s3cret")


@pytest.fixture
async def secured(secured_container):
    c = secured_container
    app = create_app(c)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as cl:
        yield cl, c


AUTH = {"Authorization": "Bearer s3cret"}


async def test_admin_auth(secured):
    cl, _ = secured
    assert (await cl.get("/api/admin/stats")).status_code == 401
    assert (await cl.get("/api/admin/stats", headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await cl.get("/api/admin/stats", headers=AUTH)).status_code == 200
    assert (await cl.post("/api/chat/sync", json={"message": Q})).status_code == 200  # chat sin auth


async def test_admin_open_without_token(client):
    assert (await client.get("/api/admin/stats")).status_code == 200


async def test_stats(secured):
    cl, _ = secured
    s = (await cl.get("/api/admin/stats", headers=AUTH)).json()
    assert s["sources"] == 1 and s["documents_active"] == 1 and s["chunks_active"] >= 1


async def test_documents_read_only(secured):
    cl, _ = secured
    assert (await cl.get("/api/admin/documents")).status_code == 401
    page = (await cl.get("/api/admin/documents", headers=AUTH)).json()
    assert page["total"] == 1 and page["items"][0]["source_id"] == "reg"
    assert (await cl.get("/api/admin/documents?source_id=otra", headers=AUTH)).json()["total"] == 0
    doc_id = page["items"][0]["doc_id"]
    body = (await cl.get(f"/api/admin/documents/{doc_id}/chunks", headers=AUTH)).json()
    assert body["document"]["doc_id"] == doc_id
    assert body["chunks"] and "reserva de matrícula" in body["chunks"][0]["text"]
    assert (await cl.get("/api/admin/documents/nope/chunks", headers=AUTH)).status_code == 404


async def test_put_schedule_applies_hot(secured):
    cl, c = secured
    assert (await cl.get("/api/admin/schedule", headers=AUTH)).json()["interval_minutes"] == 60
    r = await cl.put("/api/admin/schedule", headers=AUTH,
                     json={"enabled": True, "interval_minutes": 15, "cron": "0 3 * * *"})
    assert r.status_code == 200 and r.json()["next_run"] and r.json()["cron"] == "0 3 * * *"
    assert c.scheduler.applied[-1].interval_minutes == 15 and c.scheduler.applied[-1].cron == "0 3 * * *"
    assert (await c.settings_repo.get_schedule()).cron == "0 3 * * *"
    for bad in ({"interval_minutes": 0}, {"cron": "esto no es cron"}, {"cron": "* * *"}):
        assert (await cl.put("/api/admin/schedule", headers=AUTH, json=bad)).status_code == 422
    assert len(c.scheduler.applied) == 1


async def test_sources_crud(secured):
    cl, c = secured
    new = {"id": "avisos", "url": "https://unsa.test/avisos", "authority": "low"}
    r = await cl.post("/api/admin/sources", headers=AUTH, json=new)
    assert r.status_code == 201 and r.json()["name"] == "avisos"
    assert (await cl.post("/api/admin/sources", headers=AUTH, json=new)).status_code == 409
    assert len((await cl.get("/api/admin/sources", headers=AUTH)).json()) == 2
    assert (await cl.get("/api/admin/sources/avisos", headers=AUTH)).json()["authority"] == "low"
    r = await cl.put("/api/admin/sources/avisos", headers=AUTH, json={**new, "enabled": False})
    assert r.json()["enabled"] is False
    assert (await cl.put("/api/admin/sources/zzz", headers=AUTH, json={**new, "id": "zzz"})).status_code == 404
    assert (await cl.put("/api/admin/sources/avisos", headers=AUTH, json={**new, "id": "otro"})).status_code == 422
    assert (await cl.delete("/api/admin/sources/avisos", headers=AUTH)).status_code == 204
    assert (await cl.get("/api/admin/sources/avisos", headers=AUTH)).status_code == 404
    assert (await cl.delete("/api/admin/sources/avisos", headers=AUTH)).status_code == 404


async def test_update_wait_and_background(secured):
    cl, c = secured
    r = await cl.post("/api/admin/update?wait=true", headers=AUTH, json={"force": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["sources"][0]["source_id"] == "reg" and body["sources"][0]["documents_unchanged"] == 1
    r = await cl.post("/api/admin/update", headers=AUTH)
    assert r.status_code == 202
    reports = (await cl.get("/api/admin/reports?limit=5", headers=AUTH)).json()
    assert len(reports) >= 2 and "started_at" in reports[0]
