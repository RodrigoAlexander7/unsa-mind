from __future__ import annotations

import pytest

from unsa_mind.adapters.scraping.html_parser import HtmlParser
from unsa_mind.domain.entities import RawDocument
from unsa_mind.domain.errors import ParseError


def page(extra: str = "", minutes: int = 5) -> bytes:
    return f"""<!doctype html><html><head><title>Admisión 2026 | UNSA</title>
<style>.x{{}}</style><script>var a=1;</script></head><body>
<div class="cookie-banner">Usamos cookies. Aceptar</div>
<nav><ul><li><a href="/">Inicio</a></li><li><a href="/x">Contacto</a></li></ul></nav>
<div class="main-menu">Menú repetido</div>
<main>
<h1>Proceso de Admisión</h1>
<p>Publicado hace {minutes} minutos</p>
<h2>Requisitos</h2>
<p>Presentar   DNI y   certificado.</p>
<h3>Documentos</h3>
<ul><li>DNI</li><li>Foto</li></ul>
<table><tr><th>Modalidad</th><th>Vacantes</th></tr><tr><td>CEPRU</td><td>100</td></tr></table>
{extra}
</main>
<footer>Copyright UNSA. Todos los derechos</footer>
</body></html>""".encode()


def parse(body: bytes):
    raw = RawDocument(source_id="s", url="https://unsa.edu.pe/adm", content_type="text/html", body=body)
    return HtmlParser().parse(raw, base_metadata={"facultad": "X"})


def test_hierarchy_table_and_cleaning():
    doc = parse(page())
    md = doc.markdown
    assert doc.title == "Admisión 2026 | UNSA"
    assert "# Proceso de Admisión" in md
    assert "\n## Requisitos" in md
    assert "\n### Documentos" in md
    assert "| Modalidad | Vacantes |" in md and "| CEPRU | 100 |" in md
    assert "Presentar DNI y certificado." in md
    for noise in ("cookies", "Inicio", "Menú repetido", "Copyright", "var a=1"):
        assert noise not in md
    assert doc.metadata == {"facultad": "X"}


def test_hash_stable_against_noise():
    a = parse(page(minutes=5))
    b = parse(page(minutes=47))
    assert a.content_hash == b.content_hash


def test_hash_changes_on_real_change():
    assert parse(page()).content_hash != parse(page("<p>Nueva fecha de examen</p>")).content_hash


def test_title_falls_back_to_h1():
    doc = parse(b"<html><body><h1>Solo H1</h1><p>texto</p></body></html>")
    assert doc.title == "Solo H1"


def test_empty_raises():
    with pytest.raises(ParseError):
        parse(b"<html><body><script>x</script></body></html>")


def test_supports():
    p = HtmlParser()
    assert p.supports("text/html; charset=utf-8") and not p.supports("application/pdf")
