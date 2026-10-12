"""Utilidades SQLite compartidas: conexión por operación, WAL y migraciones simples."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


class Database:
    """Acceso a un archivo SQLite desde asyncio.

    Una conexión nueva por operación (barata en SQLite) ejecutada en un hilo; un lock
    serializa las escrituras para evitar `database is locked` dentro del proceso.
    """

    def __init__(self, path: Path | str, migrations: Sequence[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._migrate(migrations)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _migrate(self, migrations: Sequence[str]) -> None:
        with self._write_lock:
            conn = self.connect()
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
                row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
                current = row["v"] or 0
                for i, script in enumerate(migrations, start=1):
                    if i <= current:
                        continue
                    conn.executescript(script)
                    conn.execute("INSERT INTO schema_version(version) VALUES (?)", (i,))
                    conn.commit()
            finally:
                conn.close()

    def run_sync(self, fn: Callable[[sqlite3.Connection], T], *, write: bool) -> T:
        """Ejecuta `fn(conn)` (pensado para correr dentro de asyncio.to_thread)."""
        if write:
            self._write_lock.acquire()
        conn = self.connect()
        try:
            result = fn(conn)
            if write:
                conn.commit()
            return result
        except Exception:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()
            if write:
                self._write_lock.release()
