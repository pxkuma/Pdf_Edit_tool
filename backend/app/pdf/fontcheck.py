"""Verify which glyphs really exist in an embedded (often subsetted) font program.

Many subsetters keep the full ToUnicode map or keep glyph slots but empty their
outlines. Emitting such a code would render nothing, so before re-using an
embedded font we drop every mapping whose glyph has no outline.

Glyph lookup follows ISO 32000-1 9.6.6.4 (simple TrueType) and the glyph-name
model of Type1/CFF fonts. A code whose glyph cannot be located is treated as
missing: the editor then falls back to a substitute face instead of writing a
code that viewers draw as .notdef or blank.
"""

from __future__ import annotations

import logging

import pymupdf as fitz

from . import encodings, fontprog, pdfobj
from .fontprog import FontProgram

log = logging.getLogger(__name__)

FLAG_SYMBOLIC = 1 << 2


def _cid_to_gid(doc: fitz.Document, descendant: int) -> bytes | None:
    kind, value = pdfobj.get_key(doc, descendant, "CIDToGIDMap")
    if kind == "xref":
        target = pdfobj.ref_xref(value)
        if target is not None:
            try:
                return doc.xref_stream(target)
            except Exception:  # noqa: BLE001
                return None
    return None


def _type0_has_glyph(program: FontProgram, cid: int, gid_map: bytes | None, blank_ok: bool) -> bool:
    if program.is_cid_keyed:
        charset = program.cff_top.charset
        name = f"cid{cid:05d}"
        return name in charset and program.has_outline(name, blank_ok)
    if gid_map is not None and len(gid_map) >= 2 * cid + 2:
        return program.has_outline_gid(int.from_bytes(gid_map[2 * cid: 2 * cid + 2], "big"), blank_ok)
    return program.has_outline_gid(cid, blank_ok)  # Identity CIDToGIDMap / non-CID CFF: CID == GID


def filter_type0(doc: fitz.Document, xref: int, descendant: int | None, reverse: dict[str, bytes]) -> dict[str, bytes]:
    program = fontprog.load(doc, xref)
    if program is None:
        return reverse
    gid_map = _cid_to_gid(doc, descendant) if descendant else None
    try:
        return {
            text: code for text, code in reverse.items()
            if _type0_has_glyph(program, int.from_bytes(code, "big"), gid_map, text.isspace())
        }
    except Exception:  # noqa: BLE001 - verification is best effort
        log.debug("glyph verification failed for font %s", xref, exc_info=True)
        return reverse
    finally:
        program.close()


def is_symbolic(doc: fitz.Document, xref: int) -> bool:
    descriptor = pdfobj.ref_xref(pdfobj.get_key(doc, xref, "FontDescriptor")[1])
    if descriptor is None:
        return False
    flags = pdfobj.read_number_array(doc, descriptor, "Flags")
    return bool(flags) and bool(int(flags[0]) & FLAG_SYMBOLIC)


def filter_simple(program: FontProgram, reverse: dict[str, bytes], glyph_names: encodings.GlyphTable,
                  symbolic: bool) -> dict[str, bytes]:
    """Keep the mappings of a simple font whose code selects a glyph with an outline."""
    try:
        if program.tt is not None and "glyf" in program.tt:
            finder = _TrueTypeLookup(program, glyph_names, symbolic)
            return {t: c for t, c in reverse.items() if finder.has_glyph(c[0], t)}
        return {t: c for t, c in reverse.items() if program.has_outline(glyph_names.get(c[0]), t.isspace())}
    except Exception:  # noqa: BLE001 - verification is best effort
        log.debug("glyph verification failed", exc_info=True)
        return reverse


class _TrueTypeLookup:
    """Code -> glyph of a simple TrueType font (ISO 32000-1 9.6.6.4)."""

    def __init__(self, program: FontProgram, glyph_names: encodings.GlyphTable, symbolic: bool) -> None:
        font = program.tt
        self.program = program
        self.glyph_names = glyph_names
        self.tables = {(t.platformID, t.platEncID): t.cmap for t in font["cmap"].tables} if "cmap" in font else {}
        self.symbolic = symbolic or ((3, 1) not in self.tables and (1, 0) not in self.tables)
        self.order = program.glyph_order()
        self.index = {name: i for i, name in enumerate(self.order)}
        self.mac_codes = {name: code for code, name in encodings.base_glyph_table("MacRomanEncoding").items()}

    def has_glyph(self, code: int, text: str) -> bool:
        blank_ok = text.isspace()  # a space exists without drawing anything
        if not self.tables:
            return self.program.has_outline_gid(code, blank_ok)  # no cmap at all: codes are glyph indices
        name = self._symbolic_name(code) if self.symbolic else self._unicode_name(code, text)
        return name is not None and name in self.index and self.program.has_outline(name, blank_ok)

    def _symbolic_name(self, code: int) -> str | None:
        symbol = self.tables.get((3, 0))
        if symbol:
            for candidate in (code, 0xF000 + code, 0xF100 + code, 0xF200 + code):
                if candidate in symbol:
                    return symbol[candidate]
        mac = self.tables.get((1, 0))
        return mac.get(code) if mac else None

    def _unicode_name(self, code: int, text: str) -> str | None:
        glyph = self.glyph_names.get(code)
        unicode_text = encodings.glyph_to_unicode(glyph) if glyph else text
        unicode_cmap = self.tables.get((3, 1))
        if unicode_cmap and len(unicode_text) == 1 and ord(unicode_text) in unicode_cmap:
            return unicode_cmap[ord(unicode_text)]
        mac = self.tables.get((1, 0))
        if mac and glyph in self.mac_codes and self.mac_codes[glyph] in mac:
            return mac[self.mac_codes[glyph]]
        return glyph if glyph in self.index else None  # by name through the 'post' table
