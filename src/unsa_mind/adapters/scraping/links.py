"""Extracción y normalización de enlaces (compartido por los fetchers)."""

from __future__ import annotations

from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:")


def normalize_url(url: str) -> str:
    """Sin fragmento, esquema/host en minúsculas y ruta mínima '/'."""
    url, _ = urldefrag(url.strip())
    parts = urlsplit(url)
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}{query}"


def extract_links(html: str | bytes, base_url: str) -> tuple[str, ...]:
    """Enlaces absolutos http(s) del MISMO dominio, normalizados, únicos y en orden."""
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlsplit(base_url).netloc.lower()
    seen: dict[str, None] = {}
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.lower().startswith(_SKIP_SCHEMES):
            continue
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or parts.netloc.lower() != base_host:
            continue
        seen.setdefault(normalize_url(absolute), None)
    return tuple(seen)


def base_content_type(header: str | None, url: str = "") -> str:
    ct = (header or "").split(";")[0].strip().lower()
    if not ct or ct == "application/octet-stream":
        if urlsplit(url).path.lower().endswith(".pdf"):
            return "application/pdf"
        return ct or "text/html"
    return ct
