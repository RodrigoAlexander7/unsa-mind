"""HTML -> Markdown con jerarquía de títulos, tablas y limpieza de ruido."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Comment
from markdownify import markdownify

from unsa_mind.domain.entities import ParsedDocument, RawDocument, sha256
from unsa_mind.domain.errors import ParseError

_DROP_TAGS = ["script", "style", "noscript", "nav", "footer", "aside", "form", "iframe", "svg", "template", "button"]
_NOISE_ATTR = re.compile(
    r"cookie|consent|gdpr|navbar|(^|[-_ ])nav([-_ ]|$)|menu|breadcrumb|sidebar|skip-link|social|share|newsletter",
    re.IGNORECASE,
)
_RELATIVE_TIME = re.compile(
    r"\b(hace\s+\d+\s+\w+|\d+\s+(?:seconds?|minutes?|hours?|days?)\s+ago|hace\s+un\s+momento)\b",
    re.IGNORECASE,
)
_VISITS = re.compile(r"\b\d[\d.,]*\s+(visitas|vistas|views)\b", re.IGNORECASE)


def normalize_markdown(md: str) -> str:
    """Espacios y saltos canónicos."""
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in md.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln and (not out or not out[-1]):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def stable_hash_text(md: str) -> str:
    """Texto a hashear: sin fragmentos dinámicos (tiempos relativos, contadores)."""
    return normalize_markdown(_VISITS.sub("", _RELATIVE_TIME.sub("", md)))


class HtmlParser:
    def supports(self, content_type: str) -> bool:
        return content_type.split(";")[0].strip().lower() in ("text/html", "application/xhtml+xml")

    def parse(self, raw: RawDocument, *, base_metadata: dict) -> ParsedDocument:
        soup = BeautifulSoup(raw.body, "html.parser")
        title = self._title(soup)
        for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
            c.extract()
        for tag in soup.find_all(_DROP_TAGS):
            tag.decompose()
        for tag in list(soup.find_all(True)):
            if tag.attrs is None:  # ya descartado junto a un ancestro
                continue
            if tag.name in ("html", "body", "main", "article"):
                continue
            if _NOISE_ATTR.search(" ".join(self._attr_tokens(tag))):
                tag.decompose()
        root = soup.find("main") or soup.find("article") or soup.body or soup
        for hdr in root.find_all("header"):
            if not hdr.find(["h1", "h2", "h3", "h4", "h5", "h6"]):
                hdr.decompose()
        md = markdownify(str(root), heading_style="ATX", bullets="-", strip=["img"])
        markdown = normalize_markdown(md)
        if not markdown:
            raise ParseError("documento HTML sin contenido textual")
        if not title:
            m = re.search(r"^#{1,6}\s+(.+)$", markdown, re.MULTILINE)
            title = m.group(1).strip() if m else raw.url
        return ParsedDocument(
            source_id=raw.source_id,
            url=raw.url,
            title=title,
            markdown=markdown,
            content_hash=sha256(stable_hash_text(markdown)),
            metadata=dict(base_metadata),
            fetched_at=raw.fetched_at,
        )

    @staticmethod
    def _attr_tokens(tag: Any) -> list[str]:
        attrs = tag.attrs or {}
        cls = attrs.get("class") or []
        if isinstance(cls, str):
            cls = [cls]
        return [*cls, str(attrs.get("id") or ""), str(attrs.get("role") or "")]

    @staticmethod
    def _title(soup: BeautifulSoup) -> str:
        if soup.title and soup.title.get_text(strip=True):
            return re.sub(r"\s+", " ", soup.title.get_text()).strip()
        h1 = soup.find("h1")
        return re.sub(r"\s+", " ", h1.get_text()).strip() if h1 else ""
