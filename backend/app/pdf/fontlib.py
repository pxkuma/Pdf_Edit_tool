"""Download the free font a PDF uses when it is not installed.

PDFs usually embed only a subset of each font (the characters the author used).
Typing a character outside that subset needs the real font. For free families
this module fetches complete static TrueType files from Google Fonts, so edits
continue in the very same typeface instead of a look-alike. Commercial fonts
(Arial, Calibri, ...) cannot be downloaded; the user can upload them instead.

Only ``fonts.googleapis.com`` (CSS) and ``fonts.gstatic.com`` (files) are ever
contacted, and every download is size-limited and validated as a font.
"""

from __future__ import annotations

import io
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError

from .fontres import clean_font_name, normalize_font_name
from .fonts import STYLE_WEIGHTS, FontCatalog, FontFace, weight_of

log = logging.getLogger(__name__)

GOOGLE_CSS = "https://fonts.googleapis.com/css2"
FONT_HOST = "fonts.gstatic.com"
MAX_CSS_BYTES = 256 * 1024
MAX_FONT_BYTES = 15 * 1024 * 1024
TIMEOUT_SECONDS = 15
_FAMILY_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ]{0,59}$")
_FONT_FACE = re.compile(
    r"font-style:\s*(normal|italic);\s*font-weight:\s*(\d{3});\s*src:\s*url\(([^)\s]+)\)", re.DOTALL)
_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true")

# Commercial families: never downloadable (licence), offer an upload instead.
COMMERCIAL = (
    "arial", "helvetica", "timesnewroman", "times", "calibri", "cambria", "candara", "consolas",
    "constantia", "corbel", "segoe", "verdana", "tahoma", "georgia", "trebuchet", "garamond",
    "bookantiqua", "couriernew", "courier", "futura", "gillsans", "myriad", "minion", "frutiger",
    "avenir", "century", "franklingothic", "palatino", "lucida", "symbol", "zapfdingbats",
    "wingdings", "webdings", "msmincho", "msgothic", "simsun", "simhei", "mangal", "aptos",
    "bahnschrift", "sylfaen", "impact", "comicsans", "bookman", "optima", "univers", "baskerville",
)

_STYLE_SUFFIX = re.compile(
    r"(" + "|".join(sorted({w for w, _ in STYLE_WEIGHTS} | {"italic", "oblique", "it", "mt", "ps", "psmt"},
                           key=len, reverse=True)) + r")$", re.IGNORECASE)


class FontLibraryError(Exception):
    """A font could not be looked up or downloaded (message is user-facing)."""


class FontNotFound(FontLibraryError):
    pass


class FontLibraryOffline(FontLibraryError):
    pass


Fetch = Callable[[str, int], bytes]


@dataclass(frozen=True)
class FontLookup:
    name: str  # the PDF's font name, cleaned
    family: str  # family to download / that is installed
    status: str  # installed | downloadable | commercial | unknown | offline
    substitute: str | None  # installed family used meanwhile


def fetch_url(url: str, limit: int) -> bytes:
    """GET ``url`` (https only), at most ``limit`` bytes."""
    if not url.startswith("https://"):
        raise FontLibraryError("Refusing a non-HTTPS font download.")
    request = urllib.request.Request(url, headers={"User-Agent": "PDFStudio/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404):
            raise FontNotFound(url) from exc
        raise FontLibraryOffline(f"The font library answered with HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FontLibraryOffline("The font library could not be reached. Check the internet connection.") from exc
    if len(data) > limit:
        raise FontLibraryError("The font file is too large.")
    return data


# ------------------------------------------------------------------ names
def _strip_style(base: str) -> str:
    previous = None
    while previous != base:
        previous = base
        stripped = _STYLE_SUFFIX.sub("", base)
        base = stripped if len(stripped) >= 2 else base
    return base


def _spaced(name: str) -> str:
    name = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=\d)", " ", name)
    return re.sub(r"[_\s]+", " ", name).strip()


def family_candidates(pdf_name: str) -> list[str]:
    """Likely family names for a PDF font name, best first (``Montserrat-SemiBold`` -> ``Montserrat``)."""
    name = clean_font_name(pdf_name)
    base = re.split(r"[-,]", name, maxsplit=1)[0] or name
    if " " in base:
        words = base.split()
        while len(words) > 1 and _STYLE_SUFFIX.fullmatch(words[-1]):
            words.pop()  # "Montserrat SemiBold" -> "Montserrat"
        base = " ".join(words)
    else:
        base = _strip_style(base)
    result: list[str] = []
    for candidate in (_spaced(base), base, _spaced(name.split(",")[0])):
        candidate = candidate.strip()
        if candidate and candidate not in result and _FAMILY_OK.match(candidate):
            result.append(candidate)
    return result


def style_of(pdf_name: str) -> tuple[int, bool]:
    """(weight, italic) a PDF font name describes."""
    lowered = normalize_font_name(pdf_name)
    italic = "italic" in lowered or "oblique" in lowered or bool(re.search(r"(bd)?it(mt)?$", lowered))
    return weight_of(pdf_name) or 400, italic


def is_commercial(pdf_name: str) -> bool:
    candidates = family_candidates(pdf_name) or [pdf_name]
    key = normalize_font_name(candidates[0])
    return any(key == word or key.startswith(word) for word in COMMERCIAL)


# ------------------------------------------------------------------ lookup
_cache: dict[str, FontLookup] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _css_url(family: str, styles: list[tuple[int, bool]] | None) -> str:
    query = urllib.parse.quote(family, safe=" ").replace(" ", "+")
    if styles:
        spec = ";".join(f"{int(italic)},{weight}" for weight, italic in sorted(styles, key=lambda s: (s[1], s[0])))
        query += f":ital,wght@{spec}"
    return f"{GOOGLE_CSS}?family={query}"


def _faces_in_css(css: str) -> list[tuple[int, bool, str]]:
    return [(int(weight), style == "italic", url) for style, weight, url in _FONT_FACE.findall(css)]


def lookup(catalog: FontCatalog, pdf_name: str, fetch: Fetch | None = None) -> FontLookup:
    fetch = fetch or fetch_url
    name = clean_font_name(pdf_name)
    weight, italic = style_of(name)
    substitute = catalog.substitute(name, weight >= 600, italic, False, False)
    installed = catalog.exact_family(name)
    candidates = family_candidates(name)
    family = candidates[0] if candidates else name
    if installed:
        return FontLookup(name, installed, "installed", installed)
    sub = substitute.family if substitute else None
    if is_commercial(name):
        return FontLookup(name, family, "commercial", sub)
    with _lock:
        cached = _cache.get(name)
    if cached and cached.status != "offline":
        return cached
    result = FontLookup(name, family, "unknown", sub)
    for candidate in candidates:
        try:
            if _faces_in_css(fetch(_css_url(candidate, None), MAX_CSS_BYTES).decode("utf-8", "replace")):
                result = FontLookup(name, candidate, "downloadable", sub)
                break
        except FontNotFound:
            continue
        except FontLibraryOffline:
            return FontLookup(name, family, "offline", sub)
    with _lock:
        _cache[name] = result
    return result


# ------------------------------------------------------------------ download
def _wanted_styles(pdf_name: str) -> list[tuple[int, bool]]:
    used = style_of(pdf_name)
    styles = [used, (400, False), (700, False), (400, True), (700, True)]
    return list(dict.fromkeys(styles))


def _validated_font(data: bytes, family: str) -> None:
    if data[:4] not in _MAGIC:
        raise FontLibraryError("The downloaded file is not a font.")
    try:
        font = TTFont(io.BytesIO(data), lazy=True)
        names = font["name"]
        found = names.getDebugName(16) or names.getDebugName(1) or ""
        font.close()
    except (TTLibError, KeyError, ValueError, AssertionError) as exc:
        raise FontLibraryError("The downloaded font could not be read.") from exc
    if normalize_font_name(family) not in normalize_font_name(found):
        raise FontLibraryError(f"The downloaded font is “{found}”, not “{family}”.")


def download(catalog: FontCatalog, pdf_name: str, target_dir: Path, fetch: Fetch | None = None) -> list[FontFace]:
    """Install the family a PDF font belongs to (its weight plus regular/bold/italic)."""
    fetch = fetch or fetch_url
    result = lookup(catalog, pdf_name, fetch)
    if result.status == "installed":
        return [f for f in catalog.faces() if f.family == result.family]
    if result.status == "commercial":
        raise FontLibraryError(f"{result.family} is a commercial font and cannot be downloaded. Upload the font file instead.")
    if result.status == "offline":
        raise FontLibraryOffline("The font library could not be reached. Check the internet connection.")
    if result.status != "downloadable":
        raise FontNotFound(f"{result.family} was not found in the free font library.")
    family = result.family
    target_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "", family)
    faces: list[FontFace] = []
    for weight, italic in _wanted_styles(pdf_name):
        try:
            css = fetch(_css_url(family, [(weight, italic)]), MAX_CSS_BYTES).decode("utf-8", "replace")
        except FontNotFound:
            continue  # this family has no such weight/style
        for _w, _i, url in _faces_in_css(css)[:1]:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != FONT_HOST:
                raise FontLibraryError("The font library returned an unexpected download address.")
            data = fetch(url, MAX_FONT_BYTES)
            _validated_font(data, family)
            path = target_dir / f"gf-{slug}-{weight}{'i' if italic else ''}.ttf"
            path.write_bytes(data)
            face = catalog.add_user_font(path)
            if face is None:
                path.unlink(missing_ok=True)
                raise FontLibraryError("The downloaded font could not be installed.")
            faces.append(face)
    if not faces:
        raise FontNotFound(f"{family} has no downloadable styles.")
    log.info("Installed %d style(s) of %s", len(faces), family)
    clear_cache()
    return faces
