from datetime import datetime, timezone

from unsa_mind.adapters.memory import InMemorySourceRepository
from unsa_mind.adapters.persistence import build_repositories
from unsa_mind.adapters.persistence.sqlite_repos import (
    SqliteDocumentRepository,
    SqliteSettingsRepository,
    SqliteSourceRepository,
)
from unsa_mind.config.settings import Settings
from unsa_mind.domain.entities import (
    Authority,
    DocKind,
    DocumentRecord,
    Schedule,
    Source,
    SourceReport,
    UpdateReport,
)

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _settings(tmp_path, **kw):
    return Settings(data_dir=tmp_path, _env_file=None, **kw)


async def test_source_roundtrip_and_order(tmp_path):
    src, _, _ = build_repositories(_settings(tmp_path))
    a = Source(
        id="a", name="Reglamento", url="https://x/a.pdf", kind=DocKind.PDF,
        authority=Authority.HIGH, metadata={"facultad": "Ingeniería", "n": 3},
        follow_links=True, link_pattern=r"\.pdf$", max_pages=5, interval_minutes=60,
        enabled=True, last_run_at=NOW,
    )
    b = Source(id="b", name="Noticias", url="https://x/b", enabled=False)
    await src.save_source(a)
    await src.save_source(b)
    assert await src.get_source("a") == a
    assert [s.id for s in await src.list_sources()] == ["a", "b"]
    assert [s.id for s in await src.list_sources(enabled_only=True)] == ["a"]
    a.name = "Nuevo"
    await src.save_source(a)  # upsert conserva el orden
    assert (await src.get_source("a")).name == "Nuevo"
    assert [s.id for s in await src.list_sources()] == ["a", "b"]
    await src.delete_source("a")
    assert await src.get_source("a") is None


async def test_documents(tmp_path):
    _, docs, _ = build_repositories(_settings(tmp_path))
    d1 = DocumentRecord("d1", "s", "https://x/1", "T", "h1", 1, NOW)
    await docs.save(d1)
    assert await docs.get_active("https://x/1") == d1
    await docs.deactivate("d1")
    assert await docs.get_active("https://x/1") is None
    d2 = DocumentRecord("d2", "s", "https://x/1", "T", "h2", 2, NOW)
    await docs.save(d2)
    assert (await docs.get_active("https://x/1")).doc_id == "d2"
    assert len(await docs.list_documents()) == 1
    assert len(await docs.list_documents(active_only=False)) == 2


async def test_schedule_persists_across_reopen(tmp_path):
    _, _, cfg = build_repositories(_settings(tmp_path))
    assert not await cfg.has_schedule()
    assert await cfg.get_schedule() == Schedule()
    await cfg.save_schedule(Schedule(enabled=False, interval_minutes=30, cron="0 3 * * *"))
    _, _, cfg2 = build_repositories(_settings(tmp_path))
    assert await cfg2.has_schedule()
    assert await cfg2.get_schedule() == Schedule(False, 30, "0 3 * * *")


async def test_reports(tmp_path):
    _, _, cfg = build_repositories(_settings(tmp_path))
    for i in range(3):
        await cfg.save_report(
            UpdateReport(
                started_at=NOW.replace(minute=i),
                finished_at=NOW.replace(minute=i, second=9),
                sources=[SourceReport("s", pages_fetched=i, errors=["boom"] if i == 2 else [])],
            )
        )
    reports = await cfg.list_reports(limit=2)
    assert [r.started_at.minute for r in reports] == [2, 1]  # más reciente primero
    assert reports[0].sources[0].errors == ["boom"] and not reports[0].ok
    assert reports[1].ok and reports[1].sources[0].pages_fetched == 1


async def test_factory(tmp_path):
    src, docs, cfg = build_repositories(_settings(tmp_path, repository="memory"))
    assert isinstance(src, InMemorySourceRepository)
    src, docs, cfg = build_repositories(_settings(tmp_path, repository="sqlite"))
    assert isinstance(src, SqliteSourceRepository)
    assert isinstance(docs, SqliteDocumentRepository)
    assert isinstance(cfg, SqliteSettingsRepository)
    assert (tmp_path / "unsa_mind.db").exists()
