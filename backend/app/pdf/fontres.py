"""Analysis of fonts that already live inside a PDF.

``EmbeddedFont`` knows how to turn unicode text into the exact character codes of
an existing PDF font resource and how wide those glyphs are. That allows edited
text to be written with the *original* font object, pixel-identical to the
surrounding text, instead of an approximation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf as fitz

from . import cmap, fontcheck, pdfobj

SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
TAG_KEY = "PDFStudioFont"


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

    def code_for(self, char: str) -> bytes | None:
        return self.reverse.get(char)

    def width_of(self, code: bytes) -> float:
        """Advance width of a code in 1/1000 em."""
        return self.widths.get(code, self.default_width) * self.width_scale

    def coverage(self, text: str) -> float:
        chars = [c for c in text if not c.isspace()]
        if not chars:
            return 1.0
        return sum(1 for c in chars if c in self.reverse) / len(chars)


def analyze_font(doc: fitz.Document, xref: int) -> EmbeddedFont | None:
    subtype = pdfobj.read_name(doc, xref, "Subtype")
    base = pdfobj.read_name(doc, xref, "BaseFont") or f"Font{xref}"
    if subtype == "Type0":
        return _analyze_type0(doc, xref, base)
    if subtype in ("TrueType", "Type1", "MMType1", "Type3"):
        return _analyze_simple(doc, xref, base, subtype)
    return None


def _tounicode(doc: fitz.Document, xref: int) -> tuple[dict[bytes, str], int | None]:
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


def _analyze_type0(doc: fitz.Document, xref: int, base: str) -> EmbeddedFont | None:
    encoding = pdfobj.read_name(doc, xref, "Encoding")
    if encoding not in ("Identity-H", "Identity-V"):
        return None
    mapping, _ = _tounicode(doc, xref)
    descendant = pdfobj.first_array_ref(doc, xref, "DescendantFonts")
    widths: dict[bytes, float] = {}
    default_width = 1000.0
    embedded = False
    if descendant is not None:
        dw = pdfobj.read_number_array(doc, descendant, "DW")
        default_width = dw[0] if dw else 1000.0
        widths = _parse_cid_widths(doc, descendant)
        embedded = _has_font_file(doc, descendant)
    reverse = _invert({k: v for k, v in mapping.items() if len(k) == 2})
    if embedded:
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


def _parse_cid_widths(doc: fitz.Document, xref: int) -> dict[bytes, float]:
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


def _analyze_simple(doc: fitz.Document, xref: int, base: str, subtype: str) -> EmbeddedFont:
    first_char = pdfobj.read_number_array(doc, xref, "FirstChar")
    widths_list = pdfobj.read_number_array(doc, xref, "Widths")
    start = int(first_char[0]) if first_char else 0
    widths = {bytes([start + i]): w for i, w in enumerate(widths_list) if 0 <= start + i < 256}
    # ToUnicode is authoritative: in subset fonts it lists exactly the glyphs present.
    # Without it we fall back to the encoding, keeping only codes with a real width
    # so we never emit a code whose glyph was stripped by the subsetter.
    mapping, _ = _tounicode(doc, xref)
    if not mapping:
        mapping = _simple_encoding(doc, xref)
        if widths:
            mapping = {code: ch for code, ch in mapping.items() if widths.get(code, 0) > 0 or ch == " "}
    reverse = _invert({k: v for k, v in mapping.items() if len(k) == 1})
    embedded = subtype == "Type3" or _has_font_file(doc, xref)
    if embedded and subtype == "TrueType":
        reverse = fontcheck.filter_simple_truetype(doc, xref, reverse)
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


def _simple_encoding(doc: fitz.Document, xref: int) -> dict[bytes, str]:
    kind, value = pdfobj.get_key(doc, xref, "Encoding")
    if kind == "name":
        return cmap.simple_encoding_map(value.lstrip("/"), None)
    if kind in ("dict", "xref"):
        target = pdfobj.ref_xref(value) if kind == "xref" else xref
        prefix = "" if kind == "xref" else "Encoding/"
        base = pdfobj.read_name(doc, target, f"{prefix}BaseEncoding") or "StandardEncoding"
        diff_kind, diff_value, _ = pdfobj.resolve(doc, target, f"{prefix}Differences")
        differences = diff_value if diff_kind != "null" else None
        return cmap.simple_encoding_map(base, differences)
    return cmap.simple_encoding_map("StandardEncoding", None)


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


def find_tagged_font(doc: fitz.Document, font_id: str, hint: int | None = None) -> int | None:
    wanted = fitz.get_pdf_str(font_id)
    if hint and 0 < hint < doc.xref_length():
        if pdfobj.get_key(doc, hint, TAG_KEY)[1] == wanted:
            return hint
    for xref in range(1, doc.xref_length()):
        kind, value = pdfobj.get_key(doc, xref, TAG_KEY)
        if kind != "null" and value == wanted:
            return xref
    return None
