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

from fontTools.ttLib import TTFont, TTLibError

from .fontres import normalize_font_name

log = logging.getLogger(__name__)

FONT_EXTENSIONS = {".ttf", ".otf"}
# Width/weight variants that only clutter the picker.
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

_BOLD_WORDS = ("bold", "black", "heavy", "semibold", "demibold", "extrabold")


def style_from_name(name: str) -> tuple[bool, bool]:
    """Infer (bold, italic) from a PostScript-ish font name like ``Arial-BoldItalicMT``."""
    lowered = name.lower()
    bold = any(word in lowered for word in _BOLD_WORDS) or bool(re.search(r"[-,]bd(it)?$", lowered))
    italic = "italic" in lowered or "oblique" in lowered or bool(re.search(r"[-,](bd)?it(mt)?$", lowered))
    return bold, italic


def _face_from_file(path: Path) -> FontFace | None:
    try:
        font = TTFont(str(path), lazy=True, fontNumber=0)
        names = font["name"]
        family = names.getDebugName(16) or names.getDebugName(1) or path.stem
        style = names.getDebugName(17) or names.getDebugName(2) or "Regular"
        os2 = font["OS/2"] if "OS/2" in font else None
        post = font["post"] if "post" in font else None
        font.close()
    except (TTLibError, OSError, KeyError, AssertionError, ValueError):
        return None
    bold = "bold" in style.lower() or "black" in style.lower() or (os2 is not None and os2.usWeightClass >= 600)
    italic = "italic" in style.lower() or "oblique" in style.lower()
    mono = bool(post and getattr(post, "isFixedPitch", 0))
    serif = _guess_serif(family, os2)
    face_id = hashlib.sha1(str(path).encode()).hexdigest()[:12]
    return FontFace(face_id, family, style, bold, italic, serif, mono, str(path))


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

    def faces(self) -> list[FontFace]:
        with self._lock:
            if self._faces is None:
                self._faces = self._load()
            return self._faces

    def add_user_font(self, path: Path) -> FontFace | None:
        face = _face_from_file(path)
        if face is None:
            return None
        user_face = FontFace(**{**asdict(face), "source": "user"})
        with self._lock:
            faces = self._faces if self._faces is not None else self._load()
            self._faces = [f for f in faces if f.id != user_face.id] + [user_face]
        return user_face

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
                    p for p in directory.rglob("*")
                    if p.suffix.lower() in FONT_EXTENSIONS and not _SKIP_STYLE.search(p.stem)
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
                cached = json.loads(self._cache_file.read_text())
                if cached.get("signature") == signature:
                    return [FontFace(**item) for item in cached["faces"]]
            except (ValueError, TypeError, OSError, KeyError, AttributeError):
                log.warning("Ignoring corrupt font cache %s", self._cache_file)
        faces = self._scan(files)
        if self._cache_file:
            try:
                self._cache_file.parent.mkdir(parents=True, exist_ok=True)
                payload = {"signature": signature, "faces": [asdict(face) for face in faces]}
                self._cache_file.write_text(json.dumps(payload))
            except OSError:
                log.warning("Could not write font cache %s", self._cache_file)
        return faces

    def _scan(self, files: list[Path]) -> list[FontFace]:
        faces: dict[tuple[str, str], FontFace] = {}
        for path in files:
            face = _face_from_file(path)
            if face and not _SKIP_STYLE.search(face.style):
                faces.setdefault((face.family, face.style), face)
        return sorted(faces.values(), key=lambda f: (f.family.lower(), f.bold, f.italic))

    # ----------------------------------------------------------- substitution
    def pick_variant(self, family: str, bold: bool, italic: bool) -> FontFace | None:
        variants = self.families().get(family)
        if not variants:
            return None

        def score(face: FontFace) -> tuple[int, int, int]:
            plain = face.style.lower() in ("regular", "bold", "italic", "bold italic", "book", "roman")
            return (int(face.bold == bold) * 2 + int(face.italic == italic) * 2, int(plain), -len(face.style))

        return max(variants, key=score)

    def substitute(self, original_name: str, bold: bool, italic: bool, serif: bool, mono: bool) -> FontFace | None:
        key = normalize_font_name(original_name)
        base_key = re.split(r"(bold|italic|oblique|regular|black|light|medium|semibold)", key)[0]
        families = self.families()
        by_norm = {normalize_font_name(name): name for name in families}
        for candidate in (key, base_key):
            if candidate in by_norm:
                return self.pick_variant(by_norm[candidate], bold, italic)
            if candidate in ALIASES and ALIASES[candidate] in families:
                return self.pick_variant(ALIASES[candidate], bold, italic)
        for alias, family in ALIASES.items():
            if base_key.startswith(alias) and family in families:
                return self.pick_variant(family, bold, italic)
        fallback = "Liberation Mono" if mono else ("Liberation Serif" if serif else "Liberation Sans")
        if fallback in families:
            return self.pick_variant(fallback, bold, italic)
        faces = self.faces()
        return faces[0] if faces else None

    def coverage_fallbacks(self) -> list[FontFace]:
        """Faces tried, in order, for characters the primary font lacks."""
        preferred = ("Noto Sans", "DejaVu Sans", "Noto Serif")
        families = self.families()
        ordered = [self.pick_variant(name, False, False) for name in preferred if name in families]
        noto_scripts = [
            f for f in self.faces()
            if f.family.startswith("Noto Sans ") and not f.bold and not f.italic
        ]
        return [face for face in ordered if face] + noto_scripts
