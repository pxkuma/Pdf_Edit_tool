"""Low-level text writer that emits raw PDF text operators.

Text is written into a fresh content stream using *any* font resource - either an
original font already embedded in the PDF (re-used through its own character
codes) or an installed TrueType/OpenType font. Characters a font cannot render
fall back, glyph by glyph, to the next font in the chain, so a word keeps its
original font for every letter that exists in the embedded subset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pymupdf as fitz

from . import fontres, pdfobj
from .fonts import FontCatalog, FontFace

SPACE_FALLBACK_WIDTH = 250.0  # 1/1000 em, used when no font supplies a space
ITALIC_SKEW = 0.21
BOLD_STROKE = 0.03  # stroke width as a fraction of font size


@dataclass(frozen=True)
class Glyph:
    font_key: str  # "" means: no glyph, only advance (e.g. missing space)
    code: bytes
    width: float  # 1/1000 em
    char: str


@dataclass(frozen=True)
class TextStyle:
    size: float
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    opacity: float = 1.0
    bold_synth: bool = False
    italic_synth: bool = False
    underline: bool = False
    strike: bool = False
    char_spacing: float = 0.0
    hscale: float = 100.0


@dataclass
class PlacedLine:
    """A line of glyphs; origin/direction are in MuPDF (unrotated, y-down) space."""

    origin: tuple[float, float]
    direction: tuple[float, float]
    glyphs: list[Glyph]
    space_extra: float = 0.0  # extra points added after each space (justify)


@dataclass
class _FaceEntry:
    face: FontFace
    font: fitz.Font


@dataclass
class FontChain:
    """Ordered list of fonts used to encode text."""

    embedded: fontres.EmbeddedFont | None
    faces: list[_FaceEntry] = field(default_factory=list)
    used_keys: set[str] = field(default_factory=set)
    missing: set[str] = field(default_factory=set)

    @classmethod
    def build(
        cls,
        catalog: FontCatalog,
        embedded: fontres.EmbeddedFont | None,
        primary: FontFace | None,
        include_coverage: bool = True,
    ) -> "FontChain":
        faces: list[FontFace] = [primary] if primary else []
        if include_coverage:
            faces += [face for face in catalog.coverage_fallbacks() if face not in faces]
        entries = []
        for face in faces:
            try:
                entries.append(_FaceEntry(face, fitz.Font(fontfile=face.path)))
            except Exception:  # noqa: BLE001 - unreadable font file
                continue
        return cls(embedded=embedded, faces=entries)

    def encode(self, text: str) -> list[Glyph]:
        glyphs: list[Glyph] = []
        for char in text:
            glyph = self._encode_char(char)
            if glyph is not None:
                glyphs.append(glyph)
        return glyphs

    def _encode_char(self, char: str) -> Glyph | None:
        if char in "\r\n":
            return None
        if self.embedded is not None:
            code = self.embedded.code_for(char)
            if code is not None:
                key = f"e{self.embedded.xref}"
                self.used_keys.add(key)
                return Glyph(key, code, self.embedded.width_of(code), char)
        if char == " " or char == "\t":
            return self._space_glyph(char)
        for entry in self.faces:
            gid = entry.font.has_glyph(ord(char))
            if gid:
                key = f"s{entry.face.id}"
                self.used_keys.add(key)
                width = entry.font.glyph_advance(ord(char)) * 1000.0
                return Glyph(key, gid.to_bytes(2, "big"), width, char)
        self.missing.add(char)
        return None

    def _space_glyph(self, char: str) -> Glyph:
        width = SPACE_FALLBACK_WIDTH
        if self.faces:
            width = self.faces[0].font.glyph_advance(32) * 1000.0 or SPACE_FALLBACK_WIDTH
        if self.embedded is not None:
            # Average-ish space for the original font: use its default width hint.
            width = width if self.embedded.subtype != "Type3" else SPACE_FALLBACK_WIDTH
        return Glyph("", b"", width * (4 if char == "\t" else 1), char)

    def face_for_key(self, key: str) -> FontFace | None:
        return next((e.face for e in self.faces if f"s{e.face.id}" == key), None)

    def ascender(self) -> float:
        if self.faces:
            return self.faces[0].font.ascender
        return 0.8

    def descender(self) -> float:
        if self.faces:
            return self.faces[0].font.descender
        return -0.2


def line_width(glyphs: list[Glyph], style: TextStyle, space_extra: float = 0.0) -> float:
    """Advance width in points of a list of glyphs under a style."""
    scale = style.hscale / 100.0
    total = 0.0
    for glyph in glyphs:
        total += glyph.width / 1000.0 * style.size
        if glyph.font_key:
            total += style.char_spacing
        if glyph.char == " ":
            total += space_extra
    return total * scale


def register_fonts(doc: fitz.Document, page: fitz.Page, chain: FontChain) -> dict[str, str]:
    """Make every font used by the chain available as a page resource."""
    names: dict[str, str] = {}
    for key in sorted(chain.used_keys):
        if key.startswith("e") and chain.embedded is not None:
            name = f"PSE{chain.embedded.xref}"
            if pdfobj.resource_exists(doc, page, "Font", name) is None:
                pdfobj.add_resource(doc, page, "Font", name, f"{chain.embedded.xref} 0 R")
            names[key] = name
        elif key.startswith("s"):
            face = chain.face_for_key(key)
            if face is not None:
                names[key] = _register_face(doc, page, face)
    return names


def _register_face(doc: fitz.Document, page: fitz.Page, face: FontFace) -> str:
    name = f"PSS{face.id}"
    xref = fontres.find_tagged_font(doc, face.id)
    if xref is None:
        xref = page.insert_font(fontname=name, fontfile=face.path)
        fontres.tag_font(doc, xref, face.id)
        _rename_inserted_font(doc, xref, face)
    elif pdfobj.resource_exists(doc, page, "Font", name) is None:
        pdfobj.add_resource(doc, page, "Font", name, f"{xref} 0 R")
    return name


def _rename_inserted_font(doc: fitz.Document, xref: int, face: FontFace) -> None:
    """Give fallback fonts a distinct name so they are never confused with an
    original embedded font of the same family (e.g. both called "Carlito Bold")."""
    # Short on purpose: MuPDF truncates font names to 31 characters.
    label = "".join(ch for ch in f"{face.family}{face.style}" if ch.isalnum())[:12]
    name = f"/PSF{face.id[:8]}-{label}"
    doc.xref_set_key(xref, "BaseFont", name)
    descendant = pdfobj.first_array_ref(doc, xref, "DescendantFonts")
    if descendant is None:
        return
    doc.xref_set_key(descendant, "BaseFont", name)
    descriptor = pdfobj.ref_xref(pdfobj.get_key(doc, descendant, "FontDescriptor")[1])
    if descriptor is not None:
        doc.xref_set_key(descriptor, "FontName", name)


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _pdf_frame(page: fitz.Page, origin: tuple[float, float], direction: tuple[float, float]):
    inverse = ~page.transformation_matrix
    o = fitz.Point(origin) * inverse
    tip = fitz.Point(origin[0] + direction[0], origin[1] + direction[1]) * inverse
    dx, dy = tip.x - o.x, tip.y - o.y
    norm = math.hypot(dx, dy) or 1.0
    return o, dx / norm, dy / norm


def _text_matrix(page: fitz.Page, line: PlacedLine, italic: bool) -> list[float]:
    o, dx, dy = _pdf_frame(page, line.origin, line.direction)
    skew = ITALIC_SKEW if italic else 0.0
    return [dx, dy, -dy + skew * dx, dx + skew * dy, o.x, o.y]


def _tj_array(glyphs: list[Glyph], style: TextStyle, space_extra: float) -> list[tuple[str, str]]:
    """Group glyphs into (font_key, TJ-array-body) runs."""
    runs: list[tuple[str, list[str]]] = []
    current_key: str | None = None
    for glyph in glyphs:
        key = glyph.font_key or (current_key or "")
        if key != current_key or not runs:
            runs.append((key, []))
            current_key = key
        parts = runs[-1][1]
        if glyph.font_key:
            parts.append(f"<{glyph.code.hex()}>")
        else:
            gap = glyph.width + (style.char_spacing * 1000.0 / style.size if style.size else 0)
            parts.append(_fmt(-gap))
        if glyph.char == " " and space_extra and style.size:
            parts.append(_fmt(-space_extra * 1000.0 / style.size))
    return [(key, " ".join(parts)) for key, parts in runs]


def build_content(
    page: fitz.Page,
    lines: list[PlacedLine],
    style: TextStyle,
    font_names: dict[str, str],
    gstate_name: str | None,
) -> bytes:
    r, g, b = (_fmt(c) for c in style.color)
    out: list[str] = ["q"]
    if gstate_name:
        out.append(f"/{gstate_name} gs")
    out.append(f"{r} {g} {b} rg {r} {g} {b} RG")
    if style.bold_synth:
        out.append(f"{_fmt(style.size * BOLD_STROKE)} w 1 j")
    for line in lines:
        if not line.glyphs:
            continue
        matrix = _text_matrix(page, line, style.italic_synth)
        out.append("BT")
        out.append(f"{2 if style.bold_synth else 0} Tr")
        out.append(f"{_fmt(style.char_spacing)} Tc {_fmt(style.hscale)} Tz")
        out.append(" ".join(_fmt(v) for v in matrix) + " Tm")
        fallback_name = next(iter(font_names.values()), None)
        for key, body in _tj_array(line.glyphs, style, line.space_extra):
            name = font_names.get(key) or fallback_name
            if name is None:
                continue
            out.append(f"/{name} {_fmt(style.size)} Tf [{body}] TJ")
        out.append("ET")
        out.extend(_decorations(page, line, style))
    out.append("Q")
    return "\n".join(out).encode("latin-1")


def _decorations(page: fitz.Page, line: PlacedLine, style: TextStyle) -> list[str]:
    if not (style.underline or style.strike):
        return []
    width = line_width(line.glyphs, style, line.space_extra)
    o, dx, dy = _pdf_frame(page, line.origin, line.direction)
    cm = " ".join(_fmt(v) for v in (dx, dy, -dy, dx, o.x, o.y))
    thickness = _fmt(max(style.size * 0.055, 0.4))
    ops = [f"q {cm} cm {thickness} w 0 J"]
    if style.underline:
        y = _fmt(-style.size * 0.12)
        ops.append(f"0 {y} m {_fmt(width)} {y} l S")
    if style.strike:
        y = _fmt(style.size * 0.28)
        ops.append(f"0 {y} m {_fmt(width)} {y} l S")
    ops.append("Q")
    return ops


def opacity_state(doc: fitz.Document, page: fitz.Page, opacity: float) -> str | None:
    if opacity >= 0.999:
        return None
    level = max(0, min(100, round(opacity * 100)))
    name = f"PSGa{level}"
    if pdfobj.resource_exists(doc, page, "ExtGState", name) is None:
        value = f"<</Type/ExtGState/ca {_fmt(level / 100)}/CA {_fmt(level / 100)}>>"
        pdfobj.add_resource(doc, page, "ExtGState", name, value)
    return name


def write_lines(
    doc: fitz.Document,
    page: fitz.Page,
    lines: list[PlacedLine],
    style: TextStyle,
    chain: FontChain,
) -> None:
    font_names = register_fonts(doc, page, chain)
    gstate = opacity_state(doc, page, style.opacity)
    content = build_content(page, lines, style, font_names, gstate)
    pdfobj.append_content(doc, page, content)
