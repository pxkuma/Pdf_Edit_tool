"""The PDF base encodings of simple fonts, as code -> glyph name tables.

Python codecs are *not* the PDF encodings: StandardEncoding is not Latin-1
(0x27 is quoteright, 0xAE is "fi", 0xE9 is Oslash), PDF's MacRomanEncoding
predates Apple's Euro change and lacks the Mac OS math glyphs, and
PDFDocEncoding has its own 0x80-0xA0 block. Glyph names are kept (rather than
only unicode values) so the same table can locate glyphs in a font program.
"""

from __future__ import annotations

import re
from functools import lru_cache

from fontTools import agl
from fontTools.encodings.MacRoman import MacRoman as _APPLE_MAC_ROMAN
from fontTools.encodings.StandardEncoding import StandardEncoding as _STANDARD

GlyphTable = dict[int, str]

# ISO 32000-1 Annex D.2: Mac OS Roman glyphs that MacRomanEncoding does not have.
_NOT_IN_PDF_MAC_ROMAN = {0xAD, 0xB0, 0xB2, 0xB3, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xBD, 0xC3, 0xC5, 0xC6, 0xD7, 0xF0}

# ISO 32000-1 Annex D.2: PDFDocEncoding differs from Latin-1 in 0x18-0x1F and 0x80-0xA0.
_PDFDOC_SPECIAL = {
    0x18: "breve", 0x19: "caron", 0x1A: "circumflex", 0x1B: "dotaccent", 0x1C: "hungarumlaut",
    0x1D: "ogonek", 0x1E: "ring", 0x1F: "tilde",
    0x80: "bullet", 0x81: "dagger", 0x82: "daggerdbl", 0x83: "ellipsis", 0x84: "emdash", 0x85: "endash",
    0x86: "florin", 0x87: "fraction", 0x88: "guilsinglleft", 0x89: "guilsinglright", 0x8A: "minus",
    0x8B: "perthousand", 0x8C: "quotedblbase", 0x8D: "quotedblleft", 0x8E: "quotedblright", 0x8F: "quoteleft",
    0x90: "quoteright", 0x91: "quotesinglbase", 0x92: "trademark", 0x93: "fi", 0x94: "fl", 0x95: "Lslash",
    0x96: "OE", 0x97: "Scaron", 0x98: "Ydieresis", 0x99: "Zcaron", 0x9A: "dotlessi", 0x9B: "lslash",
    0x9C: "oe", 0x9D: "scaron", 0x9E: "zcaron", 0xA0: "Euro",
}


def _name_of(char: str) -> str | None:
    return agl.UV2AGL.get(ord(char))


def _from_codec(codec: str, start: int = 32) -> GlyphTable:
    table: GlyphTable = {}
    for code in range(start, 256):
        try:
            char = bytes([code]).decode(codec)
        except UnicodeDecodeError:
            continue
        name = _name_of(char) if char.isprintable() else None
        if name:
            table[code] = name
    return table


def _from_list(names: list[str]) -> GlyphTable:
    return {code: name for code, name in enumerate(names) if name and name != ".notdef"}


@lru_cache(maxsize=None)
def _tables() -> dict[str, GlyphTable]:
    mac = _from_list(_APPLE_MAC_ROMAN)
    mac = {code: name for code, name in mac.items() if code not in _NOT_IN_PDF_MAC_ROMAN and code >= 32}
    mac[0xDB] = "currency"  # PDF keeps the pre-1998 Mac OS meaning (Apple: Euro)
    pdfdoc = _from_codec("latin-1")
    pdfdoc.pop(0x7F, None)
    pdfdoc.pop(0xAD, None)
    pdfdoc.update(_PDFDOC_SPECIAL)
    winansi = _from_codec("cp1252")
    winansi.pop(0xAD, None)  # soft hyphen: invisible in most viewers
    return {
        "StandardEncoding": _from_list(_STANDARD),
        "WinAnsiEncoding": winansi,
        "MacRomanEncoding": mac,
        "PDFDocEncoding": pdfdoc,
    }


def base_glyph_table(name: str) -> GlyphTable:
    """Glyph names of a named base encoding; empty for unknown names (never guess)."""
    return dict(_tables().get(name, {}))


def standard_names() -> list[str]:
    return list(_STANDARD)


def glyph_to_unicode(glyph: str) -> str:
    """Unicode text of a glyph name (AGL, ``uniXXXX``, ``uXXXXX``, ``f_i`` ligatures)."""
    if not glyph or glyph == ".notdef":
        return ""
    try:
        text = agl.toUnicode(glyph)
    except (ValueError, OverflowError):
        text = ""
    if text:
        return text
    match = re.fullmatch(r"(?:uni|u)([0-9A-Fa-f]{4,6})", glyph)
    if match:
        value = int(match.group(1), 16)
        return chr(value) if value <= 0x10FFFF and not 0xD800 <= value <= 0xDFFF else ""
    return ""


def to_unicode_table(glyphs: GlyphTable) -> dict[int, str]:
    result: dict[int, str] = {}
    for code, name in glyphs.items():
        text = glyph_to_unicode(name)
        if text and all(ch.isprintable() for ch in text):
            result[code] = text
    return result
