"""Compact embedding of the installed faces used as fallback fonts.

``page.insert_font`` embeds the whole font file together with widths and a
ToUnicode entry for every glyph: about 400 KB for Liberation Sans and 16 MB for
a Noto CJK face, stored again in every undo version. Instead each face is
embedded as a subset holding only the glyphs the document uses:

* the program is subset with *retained glyph ids*, so the codes (= glyph ids,
  Identity-H) already written by earlier edits stay valid;
* ``/W`` and the ToUnicode CMap list exactly the embedded glyphs, which makes
  ``/W`` the record of what the subset holds;
* when a later edit needs more glyphs, the program is subset again from the
  installed file with the union of old and new glyphs.

Fonts marked with ``SUBSET_KEY`` are managed this way. Fonts inserted by older
versions (whole program, full ``/W``) are left untouched.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Mapping

import pymupdf as fitz
from fontTools import subset
from fontTools.ttLib import TTFont

from . import cmap, fontres, pdfobj

log = logging.getLogger(__name__)

SUBSET_KEY = "PDFStudioSubset"
# fontTools logs a warning for every table it cannot subset (e.g. FFTM): noise.
logging.getLogger("fontTools.subset").setLevel(logging.ERROR)

# gid -> (text drawn by the glyph, advance width in 1/1000 em)
GlyphUse = Mapping[int, tuple[str, float]]


def _subset_options() -> subset.Options:
    options = subset.Options()
    options.retain_gids = True  # codes written earlier keep pointing at their glyph
    options.notdef_outline = True
    options.layout_features = []  # text is written glyph by glyph: no shaping tables needed
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.ignore_missing_glyphs = True
    return options


def subset_program(path: str, gids: set[int]) -> bytes | None:
    """The font at ``path`` reduced to ``gids`` (glyph ids unchanged), or None on failure."""
    try:
        font = TTFont(path, lazy=True, recalcTimestamp=False)
        try:
            subsetter = subset.Subsetter(_subset_options())
            subsetter.populate(gids=sorted({0, *gids}))
            subsetter.subset(font)
            out = io.BytesIO()
            font.save(out)
            return out.getvalue()
        finally:
            font.close()
    except Exception:  # noqa: BLE001 - fontTools raises many kinds of errors on odd fonts
        log.warning("Could not subset %s; embedding the whole font", path, exc_info=True)
        return None


def program_for(path: str, gids: set[int]) -> bytes:
    """Subset program for ``gids``; the whole file when subsetting fails."""
    data = subset_program(path, gids)
    if data is not None:
        return data
    with open(path, "rb") as handle:
        return handle.read()


def is_managed(doc: fitz.Document, xref: int) -> bool:
    return pdfobj.get_key(doc, xref, SUBSET_KEY)[0] != "null"


def _descendant(doc: fitz.Document, xref: int) -> int | None:
    return pdfobj.first_array_ref(doc, xref, "DescendantFonts")


def embedded_widths(doc: fitz.Document, xref: int) -> dict[int, float]:
    """Glyph id -> width of the glyphs listed in the font's ``/W``."""
    descendant = _descendant(doc, xref)
    if descendant is None:
        return {}
    return {int.from_bytes(code, "big"): width for code, width in fontres.parse_cid_widths(doc, descendant).items()}


def _fmt(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _w_array(widths: Mapping[int, float]) -> str:
    """A compact ``/W`` array: consecutive glyph ids share one ``c [w1 w2 ...]`` entry."""
    parts: list[str] = []
    run: list[int] = []
    for gid in sorted(widths):
        if run and gid != run[-1] + 1:
            parts.append(f"{run[0]} [{' '.join(_fmt(widths[g]) for g in run)}]")
            run = []
        run.append(gid)
    if run:
        parts.append(f"{run[0]} [{' '.join(_fmt(widths[g]) for g in run)}]")
    return f"[{' '.join(parts)}]"


def _font_file_xref(doc: fitz.Document, descendant: int) -> tuple[int | None, str]:
    descriptor = pdfobj.ref_xref(pdfobj.get_key(doc, descendant, "FontDescriptor")[1])
    if descriptor is None:
        return None, ""
    for key in ("FontFile2", "FontFile3", "FontFile"):
        target = pdfobj.ref_xref(pdfobj.get_key(doc, descriptor, key)[1])
        if target is not None:
            return target, key
    return None, ""


def _write_program(doc: fitz.Document, descendant: int, data: bytes) -> None:
    target, key = _font_file_xref(doc, descendant)
    if target is None:
        return
    doc.update_stream(target, data)
    if key == "FontFile2":
        doc.xref_set_key(target, "Length1", str(len(data)))


def _write_tables(doc: fitz.Document, xref: int, descendant: int, widths: Mapping[int, float],
                  texts: Mapping[int, str]) -> None:
    w_kind, w_value = pdfobj.get_key(doc, descendant, "W")
    w_target = pdfobj.ref_xref(w_value) if w_kind == "xref" else None
    array = _w_array(widths)
    if w_target is not None:
        doc.update_object(w_target, array)
    else:
        doc.xref_set_key(descendant, "W", array)
    tounicode = cmap.build_tounicode({gid.to_bytes(2, "big"): text for gid, text in texts.items() if text}, 2)
    tu_target = pdfobj.ref_xref(pdfobj.get_key(doc, xref, "ToUnicode")[1])
    if tu_target is None:
        tu_target = doc.get_new_xref()
        doc.update_object(tu_target, "<<>>")
        doc.xref_set_key(xref, "ToUnicode", f"{tu_target} 0 R")
    doc.update_stream(tu_target, tounicode.encode("ascii"))


def _existing_texts(doc: fitz.Document, xref: int) -> dict[int, str]:
    mapping, _ = fontres.read_tounicode(doc, xref)
    return {int.from_bytes(code, "big"): text for code, text in mapping.items() if len(code) == 2}


def insert_face(page: fitz.Page, name: str, path: str, used: GlyphUse) -> int:
    """Insert the face at ``path`` as a page font holding only the ``used`` glyphs."""
    doc = page.parent
    objects = doc.xref_length()
    data = program_for(path, set(used))
    xref = page.insert_font(fontname=name, fontbuffer=data)
    if xref < objects:  # MuPDF re-used the page's existing font of that resource name
        ensure_glyphs(doc, xref, path, used)
        return xref
    descendant = _descendant(doc, xref)
    if descendant is None:  # not the Type0 font MuPDF always makes: leave it as inserted
        return xref
    doc.xref_set_key(xref, SUBSET_KEY, "true")
    _write_tables(doc, xref, descendant, {gid: width for gid, (_, width) in used.items()},
                  {gid: text for gid, (text, _) in used.items()})
    return xref


def ensure_glyphs(doc: fitz.Document, xref: int, path: str, used: GlyphUse) -> None:
    """Make sure the managed subset font ``xref`` holds every glyph in ``used``."""
    if not used or not is_managed(doc, xref):
        return
    descendant = _descendant(doc, xref)
    if descendant is None:
        return
    widths = embedded_widths(doc, xref)
    texts = _existing_texts(doc, xref)
    new = {gid: value for gid, value in used.items() if gid not in widths}
    missing_text = {gid: value[0] for gid, value in used.items() if gid in widths and not texts.get(gid)}
    if not new and not missing_text:
        return
    if new:
        widths = {**widths, **{gid: width for gid, (_, width) in new.items()}}
        _write_program(doc, descendant, program_for(path, set(widths)))
    texts = {**texts, **{gid: text for gid, (text, _) in new.items()}, **missing_text}
    _write_tables(doc, xref, descendant, widths, texts)
