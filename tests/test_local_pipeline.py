from __future__ import annotations

from unsa_mind.config.container import build_container
from unsa_mind.config.settings import Settings
from unsa_mind.domain.entities import Source


async def test_ingest_local_folder_end_to_end(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "admision.md").write_text("# Admisión\n\n## Requisitos\n\nPresentar DNI y partida.")
    s = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        raw_dir=raw,
        vector_store="memory",
        repository="memory",
        embedder_provider="hashing",
        embedder_dimension=512,
    )
    c = build_container(s, with_scheduler=False)
    src = Source(id="loc", name="Local", url=str(raw))
    r1 = await c.ingest.execute(src)
    assert r1.documents_new == 1 and not r1.errors
    r2 = await c.ingest.execute(src)  # idempotente por hash
    assert r2.documents_unchanged == 1 and r2.documents_new == 0
