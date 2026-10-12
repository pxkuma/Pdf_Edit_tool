"""Verify which glyphs really exist in an embedded (often subsetted) font program.

Many subsetters keep the full ToUnicode map or keep glyph slots but empty their
outlines. Emitting such a code would render nothing, so before re-using an
embedded font we drop every mapping whose glyph has no outline.
"""

from __future__ import annotations

import io
import logging

import pymupdf as fitz
from fontTools.ttLib import TTFont

from . import pdfobj

log = logging.getLogger(__name__)


def _load_program(doc: fitz.Document, xref: int) -> TTFont | None:
    try:
        _name, ext, _type, buffer = doc.extract_font(xref)
    except Exception:  # noqa: BLE001
        return None
    if not buffer or ext not in ("ttf", "otf", "cff"):
        return None
    if ext == "cff":
        return None  # bare CFF: glyph count check happens via widths only
    try:
        return TTFont(io.BytesIO(buffer), lazy=True)
    except Exception:  # noqa: BLE001 - malformed embedded font
        return None


def _glyph_has_outline(font: TTFont, gid: int) -> bool:
    order = font.getGlyphOrder()
    if gid < 0 or gid >= len(order):
        return False
    name = order[gid]
    if "glyf" in font:
        glyph = font["glyf"][name]
        return glyph.numberOfContours != 0
    if "CFF " in font:
        top = font["CFF "].cff.topDictIndex[0]
        strings = top.CharStrings
        if name not in strings:
            return False
        charstring = strings[name]
        charstring.decompile()
        return len(charstring.program) > 2
    return True


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


def filter_type0(doc: fitz.Document, xref: int, descendant: int | None, reverse: dict[str, bytes]) -> dict[str, bytes]:
    font = _load_program(doc, xref)
    if font is None:
        return reverse
    gid_map = _cid_to_gid(doc, descendant) if descendant else None
    is_cff_cid = "CFF " in font and getattr(font["CFF "].cff.topDictIndex[0], "ROS", None) is not None
    kept: dict[str, bytes] = {}
    try:
        for text, code in reverse.items():
            cid = int.from_bytes(code, "big")
            if text.isspace():
                kept[text] = code
                continue
            if is_cff_cid:
                charset = font["CFF "].cff.topDictIndex[0].charset
                gid = charset.index(f"cid{cid:05d}") if f"cid{cid:05d}" in charset else -1
            elif gid_map and len(gid_map) >= 2 * cid + 2:
                gid = int.from_bytes(gid_map[2 * cid: 2 * cid + 2], "big")
            else:
                gid = cid
            if _glyph_has_outline(font, gid):
                kept[text] = code
    except Exception:  # noqa: BLE001 - verification is best effort
        log.debug("glyph verification failed for font %s", xref, exc_info=True)
        return reverse
    finally:
        font.close()
    return kept


def filter_simple_truetype(doc: fitz.Document, xref: int, reverse: dict[str, bytes]) -> dict[str, bytes]:
    font = _load_program(doc, xref)
    if font is None or "glyf" not in font:
        return reverse
    kept: dict[str, bytes] = {}
    try:
        cmap_tables = {(t.platformID, t.platEncID): t.cmap for t in font["cmap"].tables} if "cmap" in font else {}
        order = font.getGlyphOrder()
        index = {name: i for i, name in enumerate(order)}
        for text, code in reverse.items():
            if text.isspace():
                kept[text] = code
                continue
            value = code[0]
            name = None
            if (3, 0) in cmap_tables:
                name = cmap_tables[(3, 0)].get(0xF000 + value) or cmap_tables[(3, 0)].get(value)
            if name is None and (1, 0) in cmap_tables:
                name = cmap_tables[(1, 0)].get(value)
            if name is None and (3, 1) in cmap_tables:
                name = cmap_tables[(3, 1)].get(ord(text[0]))
            gid = index.get(name, -1) if name is not None else value
            if _glyph_has_outline(font, gid):
                kept[text] = code
    except Exception:  # noqa: BLE001
        log.debug("glyph verification failed for font %s", xref, exc_info=True)
        return reverse
    finally:
        font.close()
    return kept
