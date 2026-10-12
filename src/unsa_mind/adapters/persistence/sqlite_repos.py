"""Repositorios SQLite (sqlite3 estándar + asyncio.to_thread, sin dependencias nuevas)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from unsa_mind.domain.entities import (
    Authority,
    DocKind,
    DocumentRecord,
    Schedule,
    Source,
    SourceReport,
    UpdateReport,
)

from ._db import Database

T = TypeVar("T")

MIGRATIONS = [
    """
    CREATE TABLE sources (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        kind TEXT NOT NULL,
        authority TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}',
        follow_links INTEGER NOT NULL DEFAULT 0,
        link_pattern TEXT,
        max_pages INTEGER NOT NULL DEFAULT 20,
        interval_minutes INTEGER,
        enabled INTEGER NOT NULL DEFAULT 1,
        last_run_at TEXT,
        position INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE documents (
        doc_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        url TEXT NOT NULL,
        title TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        version INTEGER NOT NULL,
        fetched_at TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX idx_documents_url ON documents(url, active);
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        sources TEXT NOT NULL DEFAULT '[]'
    );
    """,
]


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class _Base:
    def __init__(self, db: Database) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path | str):
        return cls(Database(path, MIGRATIONS))

    async def _read(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(self._db.run_sync, fn, write=False)

    async def _write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(self._db.run_sync, fn, write=True)


class SqliteSourceRepository(_Base):
    @staticmethod
    def _to_source(r: sqlite3.Row) -> Source:
        return Source(
            id=r["id"],
            name=r["name"],
            url=r["url"],
            kind=DocKind(r["kind"]),
            authority=Authority(r["authority"]),
            metadata=json.loads(r["metadata"]),
            follow_links=bool(r["follow_links"]),
            link_pattern=r["link_pattern"],
            max_pages=r["max_pages"],
            interval_minutes=r["interval_minutes"],
            enabled=bool(r["enabled"]),
            last_run_at=_dt(r["last_run_at"]),
        )

    async def list_sources(self, *, enabled_only: bool = False) -> list[Source]:
        def fn(c: sqlite3.Connection) -> list[Source]:
            sql = "SELECT * FROM sources" + (" WHERE enabled=1" if enabled_only else "")
            return [self._to_source(r) for r in c.execute(sql + " ORDER BY position, rowid")]

        return await self._read(fn)

    async def get_source(self, source_id: str) -> Source | None:
        def fn(c: sqlite3.Connection) -> Source | None:
            r = c.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
            return self._to_source(r) if r else None

        return await self._read(fn)

    async def save_source(self, source: Source) -> None:
        def fn(c: sqlite3.Connection) -> None:
            c.execute(
                """INSERT INTO sources(id,name,url,kind,authority,metadata,follow_links,
                       link_pattern,max_pages,interval_minutes,enabled,last_run_at,position)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,
                       COALESCE((SELECT MAX(position)+1 FROM sources), 0))
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, url=excluded.url,
                       kind=excluded.kind, authority=excluded.authority,
                       metadata=excluded.metadata, follow_links=excluded.follow_links,
                       link_pattern=excluded.link_pattern, max_pages=excluded.max_pages,
                       interval_minutes=excluded.interval_minutes, enabled=excluded.enabled,
                       last_run_at=excluded.last_run_at""",
                (
                    source.id,
                    source.name,
                    source.url,
                    DocKind(source.kind).value,
                    Authority(source.authority).value,
                    json.dumps(source.metadata, ensure_ascii=False),
                    int(source.follow_links),
                    source.link_pattern,
                    source.max_pages,
                    source.interval_minutes,
                    int(source.enabled),
                    _iso(source.last_run_at),
                ),
            )

        await self._write(fn)

    async def delete_source(self, source_id: str) -> None:
        await self._write(lambda c: c.execute("DELETE FROM sources WHERE id=?", (source_id,)))


class SqliteDocumentRepository(_Base):
    @staticmethod
    def _to_doc(r: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            doc_id=r["doc_id"],
            source_id=r["source_id"],
            url=r["url"],
            title=r["title"],
            content_hash=r["content_hash"],
            version=r["version"],
            fetched_at=datetime.fromisoformat(r["fetched_at"]),
            active=bool(r["active"]),
        )

    async def get_active(self, url: str) -> DocumentRecord | None:
        def fn(c: sqlite3.Connection) -> DocumentRecord | None:
            r = c.execute(
                "SELECT * FROM documents WHERE url=? AND active=1 ORDER BY version DESC", (url,)
            ).fetchone()
            return self._to_doc(r) if r else None

        return await self._read(fn)

    async def save(self, record: DocumentRecord) -> None:
        def fn(c: sqlite3.Connection) -> None:
            c.execute(
                """INSERT INTO documents(doc_id,source_id,url,title,content_hash,version,
                       fetched_at,active) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(doc_id) DO UPDATE SET source_id=excluded.source_id,
                       url=excluded.url, title=excluded.title,
                       content_hash=excluded.content_hash, version=excluded.version,
                       fetched_at=excluded.fetched_at, active=excluded.active""",
                (
                    record.doc_id,
                    record.source_id,
                    record.url,
                    record.title,
                    record.content_hash,
                    record.version,
                    record.fetched_at.isoformat(),
                    int(record.active),
                ),
            )

        await self._write(fn)

    async def deactivate(self, doc_id: str) -> None:
        await self._write(
            lambda c: c.execute("UPDATE documents SET active=0 WHERE doc_id=?", (doc_id,))
        )

    async def list_documents(self, *, active_only: bool = True) -> Sequence[DocumentRecord]:
        def fn(c: sqlite3.Connection) -> list[DocumentRecord]:
            sql = "SELECT * FROM documents" + (" WHERE active=1" if active_only else "")
            return [self._to_doc(r) for r in c.execute(sql + " ORDER BY rowid")]

        return await self._read(fn)


class SqliteSettingsRepository(_Base):
    _SCHEDULE_KEY = "schedule"
    _MAX_REPORTS = 100

    async def has_schedule(self) -> bool:
        def fn(c: sqlite3.Connection) -> bool:
            row = c.execute("SELECT 1 FROM settings WHERE key=?", (self._SCHEDULE_KEY,)).fetchone()
            return row is not None

        return await self._read(fn)

    async def get_schedule(self) -> Schedule:
        def fn(c: sqlite3.Connection) -> Schedule:
            r = c.execute(
                "SELECT value FROM settings WHERE key=?", (self._SCHEDULE_KEY,)
            ).fetchone()
            if not r:
                return Schedule()
            d = json.loads(r["value"])
            return Schedule(
                enabled=bool(d.get("enabled", True)),
                interval_minutes=int(d.get("interval_minutes", 1440)),
                cron=d.get("cron"),
            )

        return await self._read(fn)

    async def save_schedule(self, schedule: Schedule) -> None:
        value = json.dumps(
            {
                "enabled": schedule.enabled,
                "interval_minutes": schedule.interval_minutes,
                "cron": schedule.cron,
            }
        )
        await self._write(
            lambda c: c.execute(
                """INSERT INTO settings(key,value) VALUES (?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (self._SCHEDULE_KEY, value),
            )
        )

    async def save_report(self, report: UpdateReport) -> None:
        sources = json.dumps([asdict(s) for s in report.sources], ensure_ascii=False)

        def fn(c: sqlite3.Connection) -> None:
            c.execute(
                "INSERT INTO reports(started_at,finished_at,sources) VALUES (?,?,?)",
                (report.started_at.isoformat(), _iso(report.finished_at), sources),
            )
            c.execute(
                "DELETE FROM reports WHERE id NOT IN "
                "(SELECT id FROM reports ORDER BY id DESC LIMIT ?)",
                (self._MAX_REPORTS,),
            )

        await self._write(fn)

    async def list_reports(self, limit: int = 20) -> list[UpdateReport]:
        def fn(c: sqlite3.Connection) -> list[UpdateReport]:
            out = []
            for r in c.execute("SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,)):
                out.append(
                    UpdateReport(
                        started_at=datetime.fromisoformat(r["started_at"]),
                        finished_at=_dt(r["finished_at"]),
                        sources=[SourceReport(**d) for d in json.loads(r["sources"])],
                    )
                )
            return out

        return await self._read(fn)
