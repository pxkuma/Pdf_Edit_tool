"""Uniform access to the font programs embedded in a PDF.

Embedded fonts come as TrueType (FontFile2), OpenType (FontFile3/OpenType),
bare CFF (FontFile3/Type1C, CIDFontType0C) or Type1 (FontFile). ``FontProgram``
hides the differences for the two questions the editor asks: *does this glyph
really have an outline* and *what is the font's built-in encoding*.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

import pymupdf as fitz
from fontTools import t1Lib
from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont

from . import encodings

log = logging.getLogger(__name__)

# Charstring operators that draw something (Type1 and Type2). A glyph whose
# program has none of them (only width/hints/endchar) renders as nothing.
_DRAWING_OPS = frozenset({
    "rmoveto", "hmoveto", "vmoveto", "rlineto", "hlineto", "vlineto", "rrcurveto", "hvcurveto",
    "vhcurveto", "rcurveline", "rlinecurve", "vvcurveto", "hhcurveto", "flex", "hflex", "hflex1",
    "flex1", "seac", "callsubr", "callgsubr", "closepath",
})


def charstring_has_outline(charstring: Any) -> bool:
    try:
        charstring.decompile()
        program = charstring.program
    except Exception:  # noqa: BLE001 - malformed charstring
        return False
    if any(op in _DRAWING_OPS for op in program if isinstance(op, str)):
        return True
    # Type2 "endchar" with four or more arguments is an accented composite (seac).
    return len(program) >= 5 and program[-1] == "endchar"


@dataclass
class FontProgram:
    kind: str  # "truetype" | "cff" | "type1"
    tt: TTFont | None = None
    cff_top: Any = None  # fontTools TopDict for CFF data (bare or inside OpenType)
    t1: Any = None  # parsed Type1 font dictionary

    @property
    def is_cid_keyed(self) -> bool:
        return self.cff_top is not None and getattr(self.cff_top, "ROS", None) is not None

    def glyph_order(self) -> list[str]:
        if self.tt is not None:
            return self.tt.getGlyphOrder()
        if self.cff_top is not None:
            return list(self.cff_top.charset)
        return list(self.t1["CharStrings"].keys()) if self.t1 is not None else []

    def has_outline(self, name: str | None, blank_ok: bool = False) -> bool:
        """True when the named glyph exists and draws something.

        ``blank_ok`` accepts an existing glyph without outline (a space).
        """
        if not name or name == ".notdef":
            return False
        if self.tt is not None and "glyf" in self.tt:
            if name not in self.tt["glyf"].keys():
                return False
            return blank_ok or self.tt["glyf"][name].numberOfContours != 0
        strings = self._charstrings()
        if strings is None:
            return True  # no outline table we understand: cannot tell, trust the mapping
        if name not in strings:
            return False
        return blank_ok or charstring_has_outline(strings[name])

    def has_outline_gid(self, gid: int, blank_ok: bool = False) -> bool:
        order = self.glyph_order()
        return 0 < gid < len(order) and self.has_outline(order[gid], blank_ok)

    def _charstrings(self) -> Any:
        if self.cff_top is not None:
            return self.cff_top.CharStrings
        if self.t1 is not None:
            return self.t1["CharStrings"]
        return None

    def builtin_encoding(self) -> encodings.GlyphTable | None:
        """Code -> glyph name of the program's own encoding (simple fonts)."""
        if self.t1 is not None:
            return _encoding_from(self.t1.get("Encoding"))
        if self.cff_top is not None and not self.is_cid_keyed:
            return _encoding_from(getattr(self.cff_top, "Encoding", "StandardEncoding"))
        if self.tt is not None and "cmap" in self.tt:
            return _truetype_builtin(self.tt)
        return None

    def close(self) -> None:
        if self.tt is not None:
            self.tt.close()


def _encoding_from(value: Any) -> encodings.GlyphTable | None:
    if value is None or value == "StandardEncoding":
        return encodings.base_glyph_table("StandardEncoding")
    if isinstance(value, (list, tuple)):
        return {code: name for code, name in enumerate(value) if name and name != ".notdef"}
    return None  # ExpertEncoding or something unknown: never guess


def _truetype_builtin(font: TTFont) -> encodings.GlyphTable | None:
    tables = {(t.platformID, t.platEncID): t.cmap for t in font["cmap"].tables}
    symbol = tables.get((3, 0))
    if symbol:
        result = {}
        for code in range(256):
            name = symbol.get(0xF000 + code) or symbol.get(code)
            if name:
                result[code] = name
        return result
    mac = tables.get((1, 0))
    if mac:
        return {code: name for code, name in mac.items() if code < 256}
    return None


def load(doc: fitz.Document, xref: int) -> FontProgram | None:
    """Load the program embedded for font object ``xref`` (None if absent/unreadable)."""
    try:
        _name, ext, _type, buffer = doc.extract_font(xref)
    except Exception:  # noqa: BLE001
        return None
    if not buffer:
        return None
    try:
        return _parse(ext, buffer)
    except Exception:  # noqa: BLE001 - malformed embedded font
        log.debug("could not parse font program of %s", xref, exc_info=True)
        return None


def _parse(ext: str, buffer: bytes) -> FontProgram | None:
    if ext in ("ttf", "otf") or buffer[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        font = TTFont(io.BytesIO(buffer), lazy=True)
        top = font["CFF "].cff.topDictIndex[0] if "CFF " in font else None
        return FontProgram("truetype" if top is None else "cff", tt=font, cff_top=top)
    if ext == "cff" or buffer[:1] == b"\x01":
        cff = CFFFontSet()
        cff.decompile(io.BytesIO(buffer), None)
        return FontProgram("cff", cff_top=cff.topDictIndex[0])
    if ext in ("pfa", "pfb", "t1") or buffer[:2] == b"%!":
        font = t1Lib.T1Font.__new__(t1Lib.T1Font)
        font.data, font.encoding = buffer, "ascii"
        font.parse()
        return FontProgram("type1", t1=font.font)
    return None
