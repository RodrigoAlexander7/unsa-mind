from __future__ import annotations

import pytest

from unsa_mind.adapters.scraping.local_fetcher import LocalFileFetcher
from unsa_mind.adapters.scraping.text_parser import TextParser
from unsa_mind.domain.errors import FetchError


async def test_folder_lists_supported_files_only(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.md").write_text("# A\n\ntexto")
    (tmp_path / "sub" / "b.txt").write_text("hola")
    (tmp_path / "x.exe").write_bytes(b"x")
    (tmp_path / ".oculto.md").write_text("no")
    raw = await LocalFileFetcher(tmp_path).fetch(str(tmp_path), source_id="s")
    assert raw.content_type == "inode/directory"
    assert [u.rsplit("/", 1)[-1] for u in raw.links] == ["a.md", "b.txt"]


async def test_file_roundtrip_and_parse(tmp_path):
    (tmp_path / "reglamento.md").write_text("# Reglamento\n\nArtículo 1. Algo.")
    f = LocalFileFetcher(tmp_path)
    raw = await f.fetch((tmp_path / "reglamento.md").as_uri(), source_id="s")
    parsed = TextParser().parse(raw, base_metadata={"origen": "local"})
    assert parsed.title == "Reglamento" and parsed.metadata["origen"] == "local"


async def test_rejects_paths_outside_root(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    (tmp_path / "secreto.txt").write_text("x")
    with pytest.raises(FetchError):
        await LocalFileFetcher(root).fetch(str(tmp_path / "secreto.txt"), source_id="s")
    with pytest.raises(FetchError):
        await LocalFileFetcher(root).fetch(str(root / ".." / "secreto.txt"), source_id="s")
