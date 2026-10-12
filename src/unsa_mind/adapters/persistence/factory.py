from __future__ import annotations

from unsa_mind.adapters.memory import (
    InMemoryDocumentRepository,
    InMemorySettingsRepository,
    InMemorySourceRepository,
)
from unsa_mind.application.ports import (
    DocumentRepositoryPort,
    SettingsRepositoryPort,
    SourceRepositoryPort,
)
from unsa_mind.config.settings import Settings

from ._db import Database
from .sqlite_repos import (
    MIGRATIONS,
    SqliteDocumentRepository,
    SqliteSettingsRepository,
    SqliteSourceRepository,
)

DB_FILENAME = "unsa_mind.db"


def build_repositories(
    settings: Settings,
) -> tuple[SourceRepositoryPort, DocumentRepositoryPort, SettingsRepositoryPort]:
    if settings.repository == "memory":
        return (
            InMemorySourceRepository(),
            InMemoryDocumentRepository(),
            InMemorySettingsRepository(),
        )
    if settings.repository == "sqlite":
        db = Database(settings.data_dir / DB_FILENAME, MIGRATIONS)
        return (
            SqliteSourceRepository(db),
            SqliteDocumentRepository(db),
            SqliteSettingsRepository(db),
        )
    raise ValueError(f"Repositorio desconocido: {settings.repository!r}")
