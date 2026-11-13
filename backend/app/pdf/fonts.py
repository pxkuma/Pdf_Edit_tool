"""Catalog of installed font files and substitution logic.

When an embedded subset font lacks a glyph the user typed, we fall back to the
closest installed font (metric-compatible families first: Liberation for
Arial/Times/Courier, Carlito for Calibri, Caladea for Cambria, ...).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf as fitz
from fontTools.ttLib import TTFont, TTLibError

from . import fontfiles
from .fontres import clean_font_name, normalize_font_name

log = logging.getLogger(__name__)

FONT_EXTENSIONS = fontfiles.FONT_EXTENSIONS
# Width/weight *styles* that only clutter the picker. Applied to style names only:
# whole families such as "Playfair Display" or "Roboto Condensed" stay listed.
_SKIP_STYLE = re.compile(r"condensed|semicondensed|extracondensed|display|ui\b|thin|extralight", re.I)


@dataclass(frozen=True)
class FontFace:
    id: str
    family: str
    style: str
    bold: bool
    italic: bool
    serif: bool
    mono: bool
    path: str
    source: str = "system"
    index: int = 0  # face number inside a font collection (.ttc/.otc)


# Common commercial fonts mapped to installed (often metric-compatible) families.
ALIASES: dict[str, str] = {
    "arial": "Liberation Sans",
    "arialmt": "Liberation Sans",
    "helvetica": "Liberation Sans",
    "helveticaneue": "Liberation Sans",
    "verdana": "DejaVu Sans",
    "tahoma": "DejaVu Sans",
    "segoeui": "Open Sans",
    "trebuchetms": "Open Sans",
    "timesnewroman": "Liberation Serif",
    "timesnewromanps": "Liberation Serif",
    "timesnewromanpsmt": "Liberation Serif",
    "times": "Liberation Serif",
    "timesroman": "Liberation Serif",
    "georgia": "DejaVu Serif",
    "garamond": "Liberation Serif",
    "bookantiqua": "Liberation Serif",
    "couriernew": "Liberation Mono",
    "couriernewpsmt": "Liberation Mono",
    "courier": "Liberation Mono",
    "consolas": "Liberation Mono",
    "calibri": "Carlito",
    "cambria": "Caladea",
    "roboto": "Roboto",
    "opensans": "Open Sans",
    "lato": "Lato",
    "notosans": "Noto Sans",
    "notoserif": "Noto Serif",
    "dejavusans": "DejaVu Sans",
    "dejavuserif": "DejaVu Serif",
}

# Name parts that make a font a different *kind* than its family's alias target.
_NAME_KIND = {
    "mono": re.compile(r"mono|typewriter|console"),
    "narrow": re.compile(r"narrow|compressed"),
    "condensed": re.compile(r"cond"),
    "cjk": re.compile(r"cjk"),
}
_KIND_FAMILY_WORDS = {
    "mono": ("Mono",),
    "narrow": ("Narrow", "Condensed"),
    "condensed": ("Condensed", "Narrow"),
    "cjk": ("CJK SC", "CJK JP", "CJK KR", "CJK TC"),
}

_BOLD_WORDS = ("bold", "black", "heavy", "semibold", "demibold", "extrabold")

# Weight words, compound ones first ("semibold" before "bold").
STYLE_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("extrabold", 800), ("ultrabold", 800), ("semibold", 600), ("demibold", 600), ("extralight", 200),
    ("ultralight", 200), ("hairline", 100), ("bold", 700), ("black", 900), ("heavy", 900),
    ("light", 300), ("thin", 100), ("medium", 500), ("regular", 400), ("book", 400), ("normal", 400),
)


def weight_of(name: str) -> int | None:
    """CSS weight a font or style name spells out (``Montserrat-SemiBold`` -> 600), if any."""
    lowered = re.sub(r"[\s\-_,]", "", name.lower())
    return next((weight for word, weight in STYLE_WEIGHTS if word in lowered), None)


def style_from_name(name: str) -> tuple[bool, bool]:
    """Infer (bold, italic) from a PostScript-ish font name like ``Arial-BoldItalicMT``."""
    lowered = name.lower()
    bold = any(word in lowered for word in _BOLD_WORDS) or bool(re.search(r"[-,]bd(it)?$", lowered))
    italic = "italic" in lowered or "oblique" in lowered or bool(re.search(r"[-,](bd)?it(mt)?$", lowered))
    return bold, italic


# What may follow a family name without naming another face: "ArialMT", "TimesNewRomanPSMT".
_NEUTRAL_SUFFIX = re.compile(r"^(ps)?(mt)?(regular|roman|book|normal|plain)?(ps)?(mt)?$")
MUPDF_NAME_LIMIT = 31  # MuPDF keeps at most this many characters of a font name


def font_name_rank(wanted: str, name: str) -> int | None:
    """How well font ``name`` matches the span font ``wanted``.

    0: the same name. 1: the same face under a vendor suffix, or a name MuPDF
    truncated. None: another face, e.g. "Calibri" vs "Calibri-Light" or "Arial"
    vs "Arial-BoldMT" (prefix matching would switch the weight).
    """
    a, b = normalize_font_name(wanted), normalize_font_name(name)
    if not a or not b:
        return None
    if a == b:
        return 0
    shorter, longer, raw_shorter = (a, b, wanted) if len(a) < len(b) else (b, a, name)
    if not longer.startswith(shorter):
        return None
    if len(clean_font_name(raw_shorter)) >= MUPDF_NAME_LIMIT:
        return 1
    if _NEUTRAL_SUFFIX.match(longer[len(shorter):]) and style_from_name(wanted) == style_from_name(name):
        return 1
    return None


def _faces_from_file(path: Path) -> list[FontFace]:
    """Every face of a font file (one, or all faces of a collection)."""
    faces = []
    for index, font in fontfiles.open_faces(path):
        try:
            faces.append(_face_from_font(font, path, index))
        except (TTLibError, KeyError, AssertionError, ValueError, OSError, IndexError):
            continue
    return faces


def _face_from_file(path: Path) -> FontFace | None:
    faces = _faces_from_file(path)
    return faces[0] if faces else None


def _face_from_font(font: TTFont, path: Path, index: int) -> FontFace:
    names = font["name"]
    family = names.getDebugName(16) or names.getDebugName(1) or path.stem
    style = names.getDebugName(17) or names.getDebugName(2) or "Regular"
    os2 = font["OS/2"] if "OS/2" in font else None
    post = font["post"] if "post" in font else None
    bold = "bold" in style.lower() or "black" in style.lower() or (os2 is not None and os2.usWeightClass >= 600)
    italic = "italic" in style.lower() or "oblique" in style.lower()
    mono = bool(post and getattr(post, "isFixedPitch", 0))
    serif = _guess_serif(family, os2)
    key = str(path) if index == 0 else f"{path}#{index}"
    face_id = hashlib.sha1(key.encode()).hexdigest()[:12]
    return FontFace(face_id, family, style, bold, italic, serif, mono, str(path), index=index)


def _guess_serif(family: str, os2: object) -> bool:
    lowered = family.lower()
    if "sans" in lowered or "mono" in lowered:
        return False
    if "serif" in lowered or lowered in ("caladea", "gelasio", "eb garamond", "gentium plus"):
        return True
    panose = getattr(os2, "panose", None)
    family_type = getattr(panose, "bFamilyType", 0)
    serif_style = getattr(panose, "bSerifStyle", 0)
    return family_type == 2 and 2 <= serif_style <= 10


class FontCatalog:
    """Lazily-built, cached list of installed fonts."""

    def __init__(self, search_dirs: list[Path], cache_file: Path | None = None) -> None:
        self._dirs = search_dirs
        self._cache_file = cache_file
        self._faces: list[FontFace] | None = None
        self._lock = threading.Lock()
        self._opened: dict[str, fitz.Font | None] = {}
        self._fallbacks: dict[tuple[int, bool, bool, bool], tuple[FontFace, ...]] = {}
        self.version = 0  # bumped whenever fonts are added

    def faces(self) -> list[FontFace]:
        with self._lock:
            if self._faces is None:
                self._faces = self._load()
            return self._faces

    def add_user_font(self, path: Path) -> FontFace | None:
        """Register an uploaded font file; returns its first face (None if unreadable)."""
        user_faces = [FontFace(**{**asdict(face), "source": "user"}) for face in _faces_from_file(path)]
        if not user_faces:
            return None
        ids = {face.id for face in user_faces}
        with self._lock:
            faces = self._faces if self._faces is not None else self._load()
            self._faces = [f for f in faces if f.id not in ids] + user_faces
            self._opened = {k: v for k, v in self._opened.items() if k not in ids}
            self.version += 1
        return user_faces[0]

    def face_file(self, face: FontFace) -> str:
        """Path of a single-face file for ``face`` (collection faces are extracted once)."""
        cache_dir = self._cache_file.parent / "collection-faces" if self._cache_file else None
        return fontfiles.face_file(face.path, face.index, cache_dir)

    def open_font(self, face: FontFace) -> fitz.Font | None:
        """The MuPDF font of a face, opened once per catalog (None if unreadable)."""
        if face.id in self._opened:
            return self._opened[face.id]
        try:
            font = fitz.Font(fontfile=self.face_file(face))
        except Exception:  # noqa: BLE001 - unreadable font file
            log.warning("Could not open font %s", face.path, exc_info=True)
            font = None
        self._opened[face.id] = font
        return font

    def get(self, face_id: str) -> FontFace | None:
        return next((face for face in self.faces() if face.id == face_id), None)

    def families(self) -> dict[str, list[FontFace]]:
        result: dict[str, list[FontFace]] = {}
        for face in self.faces():
            result.setdefault(face.family, []).append(face)
        return result

    def _font_files(self) -> list[Path]:
        files: list[Path] = []
        for directory in self._dirs:
            if directory.exists():
                files.extend(
                    p for p in directory.rglob("*") if p.suffix.lower() in FONT_EXTENSIONS
                )
        return sorted(files)

    def _signature(self, files: list[Path]) -> str:
        digest = hashlib.sha1()
        for path in files:
            try:
                digest.update(f"{path}:{path.stat().st_size}".encode())
            except OSError:
                continue
        return digest.hexdigest()

    def _load(self) -> list[FontFace]:
        files = self._font_files()
        signature = self._signature(files)
        if self._cache_file and self._cache_file.exists():
            try:
                cached = json.loads(self._cache_file.read_text(encoding="utf-8"))
                if cached.get("signature") == signature:
                    return [FontFace(**item) for item in cached["faces"]]
            except (ValueError, TypeError, OSError, KeyError, AttributeError):
                log.warning("Ignoring corrupt font cache %s", self._cache_file)
        faces = self._scan(files)
        if self._cache_file:
            try:
                self._cache_file.parent.mkdir(parents=True, exist_ok=True)
                payload = {"signature": signature, "faces": [asdict(face) for face in faces]}
                self._cache_file.write_text(json.dumps(payload), encoding="utf-8")
            except OSError:
                log.warning("Could not write font cache %s", self._cache_file)
        return faces

    def _scan(self, files: list[Path]) -> list[FontFace]:
        faces: dict[tuple[str, str], FontFace] = {}
        for path in files:
            for face in _faces_from_file(path):
                if not _SKIP_STYLE.search(face.style):
                    faces.setdefault((face.family, face.style), face)
        return sorted(faces.values(), key=lambda f: (f.family.lower(), f.bold, f.italic))

    # ----------------------------------------------------------- substitution
    def pick_variant(self, family: str, bold: bool, italic: bool, weight: int | None = None) -> FontFace | None:
        variants = self.families().get(family)
        if not variants:
            return None

        def score(face: FontFace) -> tuple[int, int, int, int]:
            plain = face.style.lower() in ("regular", "bold", "italic", "bold italic", "book", "roman")
            closeness = -abs((weight_of(face.style) or (700 if face.bold else 400)) - weight) if weight else 0
            return (int(face.bold == bold) * 2 + int(face.italic == italic) * 2, closeness, int(plain), -len(face.style))

        return max(variants, key=score)

    def exact_family(self, original_name: str) -> str | None:
        """The installed family that *is* the PDF's font (not a look-alike), if any."""
        key = normalize_font_name(original_name)
        base_key = re.split(r"(bold|italic|oblique|regular|black|light|medium|semibold|extrabold|thin)", key)[0]
        by_norm = {normalize_font_name(name): name for name in self.families()}
        for candidate in (key, base_key, re.sub(r"(mt|ps|psmt)$", "", base_key)):
            if candidate in by_norm:
                return by_norm[candidate]
        return None

    def substitute(self, original_name: str, bold: bool, italic: bool, serif: bool, mono: bool) -> FontFace | None:
        key = normalize_font_name(original_name)
        base_key = re.split(r"(bold|italic|oblique|regular|black|light|medium|semibold)", key)[0]
        families = self.families()
        exact = self.exact_family(original_name)
        if exact:
            return self.pick_variant(exact, bold, italic, weight_of(original_name))
        for candidate in (key, base_key):
            if candidate in ALIASES and ALIASES[candidate] in families:
                return self.pick_variant(ALIASES[candidate], bold, italic)
        aliased = self._alias_family(base_key)
        if aliased:
            return self.pick_variant(aliased, bold, italic)
        mono = mono or _NAME_KIND["mono"].search(key) is not None
        serif = serif or ("serif" in key and "sans" not in key)
        fallback = "Liberation Mono" if mono else ("Liberation Serif" if serif else "Liberation Sans")
        if fallback in families:
            return self.pick_variant(fallback, bold, italic)
        faces = self.faces()
        return faces[0] if faces else None

    def _alias_family(self, base_key: str) -> str | None:
        """Installed family for a name that *starts* with an alias ("ArialNarrow").

        The longest alias wins. A name of another kind than the alias target
        (mono, narrow, condensed, CJK) only maps to a family of that same kind,
        e.g. "Liberation Sans Narrow", never to the proportional/wide family.
        """
        families = self.families()
        for alias in sorted(ALIASES, key=len, reverse=True):
            family = ALIASES[alias]
            if not base_key.startswith(alias) or family not in families:
                continue
            rest = base_key[len(alias):]
            kinds = [kind for kind, pattern in _NAME_KIND.items() if pattern.search(rest)]
            if not kinds:
                return family
            for kind in kinds:
                match = next((f"{family} {word}" for word in _KIND_FAMILY_WORDS[kind]
                              if f"{family} {word}" in families), None)
                if match:
                    return match
            return None
        return None

    def coverage_fallbacks(self, bold: bool = False, italic: bool = False, serif: bool = False) -> tuple[FontFace, ...]:
        """Faces tried, in order, for characters the primary font lacks.

        They follow the primary text's weight, slant and serif class, so a missing
        character in bold serif text is drawn in bold serif too. Cached per catalog version.
        """
        key = (self.version, bold, italic, serif)
        cached = self._fallbacks.get(key)
        if cached is not None:
            return cached
        preferred = ("Noto Serif", "DejaVu Serif", "Noto Sans", "DejaVu Sans") if serif else (
            "Noto Sans", "DejaVu Sans", "Noto Serif")
        families = self.families()
        ordered = [self.pick_variant(name, bold, italic) for name in preferred if name in families]
        scripts = [self.pick_variant(name, bold, False) for name in sorted(families, key=str.lower)
                   if name.startswith("Noto Sans ") and name not in preferred]
        result = tuple(dict.fromkeys(face for face in ordered + scripts if face))
        self._fallbacks = {k: v for k, v in self._fallbacks.items() if k[0] == self.version} | {key: result}
        return result
