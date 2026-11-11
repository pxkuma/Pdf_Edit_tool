"""Analysis of fonts that already live inside a PDF.

``EmbeddedFont`` knows how to turn unicode text into the exact character codes of
an existing PDF font resource and how wide those glyphs are. That allows edited
text to be written with the *original* font object, pixel-identical to the
surrounding text, instead of an approximation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property

import pymupdf as fitz

from . import cmap, encodings, fontcheck, fontprog, pdfobj

SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
TAG_KEY = "PDFStudioFont"

# Latin presentation forms (U+FB00-FB06) and their decompositions. ToUnicode
# CMaps map a ligature glyph to either one, and extracted text may hold either.
_LIGATURE_FORMS = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
                   "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
LIGATURE_DECOMPOSITION = dict(_LIGATURE_FORMS)
LIGATURE_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    **{form: (text,) for form, text in _LIGATURE_FORMS.items()},
    **{text: tuple(f for f, t in _LIGATURE_FORMS.items() if t == text) for text in set(_LIGATURE_FORMS.values())},
}
MAX_LIGATURE = 3


def clean_font_name(name: str) -> str:
    return SUBSET_PREFIX.sub("", name or "").replace("#20", " ").strip()


def normalize_font_name(name: str) -> str:
    return re.sub(r"[\s\-_,]", "", clean_font_name(name)).lower()


@dataclass
class EmbeddedFont:
    xref: int
    base_name: str
    subtype: str
    code_bytes: int
    reverse: dict[str, bytes] = field(default_factory=dict)
    widths: dict[bytes, float] = field(default_factory=dict)
    default_width: float = 500.0
    width_scale: float = 1.0
    embedded: bool = True

    @property
    def display_name(self) -> str:
        return clean_font_name(self.base_name)

    def code_for(self, text: str) -> bytes | None:
        """Code of a character or ligature ("fi" and U+FB01 are interchangeable)."""
        code = self.reverse.get(text)
        if code is None:
            for alternative in LIGATURE_ALTERNATIVES.get(text, ()):
                code = self.reverse.get(alternative)
                if code is not None:
                    break
        return code

    @cached_property
    def _longest_key(self) -> int:
        lengths = [len(key) for key in self.reverse if len(key) <= MAX_LIGATURE]
        if any(len(form) == 1 for form in self.reverse if form in LIGATURE_ALTERNATIVES):
            lengths.append(MAX_LIGATURE)  # a presentation form stands for its decomposition
        return max(lengths, default=1)

    def segments(self, text: str) -> list[tuple[str, bytes | None]]:
        """Split text greedily into the longest pieces (ligatures first) with a code."""
        result: list[tuple[str, bytes | None]] = []
        pos = 0
        while pos < len(text):
            for size in range(min(self._longest_key, len(text) - pos), 0, -1):
                piece = text[pos:pos + size]
                code = self.code_for(piece)
                if code is not None or size == 1:
                    result.append((piece, code))
                    pos += size
                    break
        return result

    def width_of(self, code: bytes) -> float:
        """Advance width of a code in 1/1000 em."""
        return self.widths.get(code, self.default_width) * self.width_scale

    def coverage(self, text: str) -> float:
        chars = [c for c in text if not c.isspace()]
        if not chars:
            return 1.0
        covered = sum(len(piece) for piece, code in self.segments(text) if code is not None and not piece.isspace())
        return min(1.0, covered / len(chars))


def analyze_font(doc: fitz.Document, xref: int, verify: bool = True) -> EmbeddedFont | None:
    """Analyse a font object. ``verify`` checks glyph presence in the font program
    (needed before writing with the font; not needed for width calculations)."""
    subtype = pdfobj.read_name(doc, xref, "Subtype")
    base = pdfobj.read_name(doc, xref, "BaseFont") or f"Font{xref}"
    if subtype == "Type0":
        return _analyze_type0(doc, xref, base, verify)
    if subtype in ("TrueType", "Type1", "MMType1", "Type3"):
        return _analyze_simple(doc, xref, base, subtype, verify)
    return None


def read_tounicode(doc: fitz.Document, xref: int) -> tuple[dict[bytes, str], int | None]:
    kind, value = pdfobj.get_key(doc, xref, "ToUnicode")
    target = pdfobj.ref_xref(value) if kind == "xref" else None
    if target is None:
        return {}, None
    text = pdfobj.stream_text(doc, target)
    return cmap.parse_tounicode(text), cmap.code_width(text)


def _invert(mapping: dict[bytes, str]) -> dict[str, bytes]:
    reverse: dict[str, bytes] = {}
    for code, text in sorted(mapping.items(), key=lambda item: item[0]):
        if text and text not in reverse and text != "�":
            reverse[text] = code
    return reverse


def _analyze_type0(doc: fitz.Document, xref: int, base: str, verify: bool = True) -> EmbeddedFont | None:
    encoding = pdfobj.read_name(doc, xref, "Encoding")
    if encoding not in ("Identity-H", "Identity-V"):
        return None
    mapping, _ = read_tounicode(doc, xref)
    descendant = pdfobj.first_array_ref(doc, xref, "DescendantFonts")
    widths: dict[bytes, float] = {}
    default_width = 1000.0
    embedded = False
    if descendant is not None:
        dw = pdfobj.read_number_array(doc, descendant, "DW")
        default_width = dw[0] if dw else 1000.0
        widths = parse_cid_widths(doc, descendant)
        embedded = _has_font_file(doc, descendant)
    reverse = _invert({k: v for k, v in mapping.items() if len(k) == 2})
    if embedded and verify:
        reverse = fontcheck.filter_type0(doc, xref, descendant, reverse)
    font = EmbeddedFont(
        xref=xref,
        base_name=base,
        subtype="Type0",
        code_bytes=2,
        reverse=reverse,
        widths=widths,
        default_width=default_width,
        embedded=embedded,
    )
    return font


def parse_cid_widths(doc: fitz.Document, xref: int) -> dict[bytes, float]:
    kind, value, _ = pdfobj.resolve(doc, xref, "W")
    if kind == "null":
        return {}
    tokens = re.findall(r"\[|\]|-?\d*\.?\d+", re.sub(r"\d+\s+0\s+R", " ", value))
    widths: dict[bytes, float] = {}
    pos = 1 if tokens and tokens[0] == "[" else 0
    numbers: list[float] = []
    while pos < len(tokens):
        token = tokens[pos]
        if token == "[":
            pos += 1
            start = int(numbers.pop()) if numbers else 0
            index = 0
            while pos < len(tokens) and tokens[pos] != "]":
                widths[(start + index).to_bytes(2, "big")] = float(tokens[pos])
                index += 1
                pos += 1
        elif token == "]":
            pass
        else:
            numbers.append(float(token))
            if len(numbers) == 3:
                first, last, width = int(numbers[0]), int(numbers[1]), numbers[2]
                for cid in range(first, min(last, first + 0xFFFF) + 1):
                    widths[cid.to_bytes(2, "big")] = width
                numbers = []
        pos += 1
    return widths


def _has_font_file(doc: fitz.Document, xref: int) -> bool:
    descriptor = pdfobj.ref_xref(pdfobj.get_key(doc, xref, "FontDescriptor")[1])
    if descriptor is None:
        return False
    return any(
        pdfobj.get_key(doc, descriptor, key)[0] != "null"
        for key in ("FontFile", "FontFile2", "FontFile3")
    )


def _analyze_simple(doc: fitz.Document, xref: int, base: str, subtype: str, verify: bool = True) -> EmbeddedFont:
    first_char = pdfobj.read_number_array(doc, xref, "FirstChar")
    widths_list = pdfobj.read_number_array(doc, xref, "Widths")
    start = int(first_char[0]) if first_char else 0
    widths = {bytes([start + i]): w for i, w in enumerate(widths_list) if 0 <= start + i < 256}
    embedded = subtype == "Type3" or _has_font_file(doc, xref)
    # The program is needed to verify glyphs, or for its built-in encoding.
    needs_program = verify or pdfobj.get_key(doc, xref, "ToUnicode")[0] == "null"
    program = fontprog.load(doc, xref) if embedded and needs_program and subtype != "Type3" else None
    try:
        reverse = _simple_reverse(doc, xref, base, subtype, widths, program, verify)
    finally:
        if program is not None:
            program.close()
    scale = 1.0
    if subtype == "Type3":
        matrix = pdfobj.read_number_array(doc, xref, "FontMatrix")
        scale = (matrix[0] * 1000.0) if matrix else 1.0
    font = EmbeddedFont(
        xref=xref,
        base_name=base,
        subtype=subtype,
        code_bytes=1,
        reverse=reverse,
        widths=widths,
        default_width=_standard_default_width(base) if not widths else 0.0,
        width_scale=scale,
        embedded=embedded,
    )
    if not widths:
        _fill_standard_widths(font)
    return font


def _simple_reverse(doc: fitz.Document, xref: int, base: str, subtype: str, widths: dict[bytes, float],
                    program: fontprog.FontProgram | None, verify: bool) -> dict[str, bytes]:
    # ToUnicode is authoritative: in subset fonts it lists exactly the glyphs present.
    # Without it we fall back to the encoding, keeping only codes with a real width
    # so we never emit a code whose glyph was stripped by the subsetter.
    mapping, _ = read_tounicode(doc, xref)
    glyph_names: encodings.GlyphTable | None = None
    if not mapping:
        glyph_names = _encoding_glyphs(doc, xref, base, program)
        mapping = cmap.glyph_table_to_map(glyph_names)
        if widths:
            mapping = {code: ch for code, ch in mapping.items() if widths.get(code, 0) > 0 or ch == " "}
    reverse = _invert({k: v for k, v in mapping.items() if len(k) == 1})
    if program is not None and verify:
        if glyph_names is None:
            glyph_names = _encoding_glyphs(doc, xref, base, program)
        reverse = fontcheck.filter_simple(program, reverse, glyph_names, fontcheck.is_symbolic(doc, xref))
    return reverse


def _encoding_glyphs(doc: fitz.Document, xref: int, base: str,
                     program: fontprog.FontProgram | None) -> encodings.GlyphTable:
    """Code -> glyph name of a simple font (ISO 32000-1 9.6.6: base encoding + /Differences)."""
    kind, value = pdfobj.get_key(doc, xref, "Encoding")
    if kind == "name":
        return encodings.base_glyph_table(value.lstrip("/"))
    if kind in ("dict", "xref"):
        target = pdfobj.ref_xref(value) if kind == "xref" else xref
        if target is None:
            return {}
        prefix = "" if kind == "xref" else "Encoding/"
        base_name = pdfobj.read_name(doc, target, f"{prefix}BaseEncoding")
        table = encodings.base_glyph_table(base_name) if base_name else _builtin_glyphs(base, program)
        diff_kind, diff_value, _ = pdfobj.resolve(doc, target, f"{prefix}Differences")
        return cmap.simple_glyph_names(table, diff_value if diff_kind != "null" else None)
    return _builtin_glyphs(base, program)


def _builtin_glyphs(base: str, program: fontprog.FontProgram | None) -> encodings.GlyphTable:
    """The font's built-in encoding: the program's own, else StandardEncoding.

    Symbol and ZapfDingbats have private built-in encodings we do not decode:
    an empty table makes the editor use a substitute instead of wrong glyphs.
    """
    if program is not None:
        return program.builtin_encoding() or {}
    lowered = clean_font_name(base).lower()
    if lowered.startswith(("symbol", "zapfdingbats", "dingbats", "wingdings", "webdings")):
        return {}
    return encodings.base_glyph_table("StandardEncoding")


_BASE14_PREFIX = {"courier": "co", "helvetica": "he", "arial": "he", "times": "ti"}
_BASE14_SUFFIX = {(False, False): "", (True, False): "bo", (False, True): "it", (True, True): "bi"}
_BASE14_REGULAR = {"co": "cour", "he": "helv", "ti": "tiro"}


def _base14_font(base: str) -> fitz.Font | None:
    lowered = clean_font_name(base).lower()
    if lowered.startswith("symbol"):
        return fitz.Font("symb")
    if lowered.startswith("zapfdingbats"):
        return fitz.Font("zadb")
    for key, prefix in _BASE14_PREFIX.items():
        if lowered.startswith(key):
            style = ("bold" in lowered, "italic" in lowered or "oblique" in lowered)
            suffix = _BASE14_SUFFIX[style]
            return fitz.Font(prefix + suffix if suffix else _BASE14_REGULAR[prefix])
    return None


def _standard_default_width(base: str) -> float:
    return 600.0 if "courier" in base.lower() else 500.0


def _fill_standard_widths(font: EmbeddedFont) -> None:
    reference = _base14_font(font.base_name) or fitz.Font("helv")
    for char, code in font.reverse.items():
        if len(char) == 1:
            font.widths[code] = reference.glyph_advance(ord(char)) * 1000.0


def tag_font(doc: fitz.Document, xref: int, font_id: str) -> None:
    doc.xref_set_key(xref, TAG_KEY, fitz.get_pdf_str(font_id))


def _has_tag(doc: fitz.Document, xref: int, font_id: str) -> bool:
    kind, value = pdfobj.get_key(doc, xref, TAG_KEY)
    # PyMuPDF returns PDF strings without their parentheses.
    return kind == "string" and value == font_id


def find_tagged_font(doc: fitz.Document, font_id: str, hint: int | None = None) -> int | None:
    if hint and 0 < hint < doc.xref_length() and _has_tag(doc, hint, font_id):
        return hint
    return next((xref for xref in range(1, doc.xref_length()) if _has_tag(doc, xref, font_id)), None)
