"""Fallback faces are embedded as growing subsets, not whole font files (audit C18)."""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz
import pytest
from fontkit import raw_page, spans
from fontTools.ttLib import TTFont

from app.pdf import doctools, fontres, pdfobj, textedit
from app.pdf.fonts import FontCatalog
from app.storage import serialize

HELVETICA = "<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>"
HELLO = b"BT /F1 24 Tf 72 700 Td (Hello World) Tj ET"
# Way below the ~400 KB a whole Liberation Sans / DejaVu Sans file adds.
MAX_GROWTH = 60_000


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> FontCatalog:
    cache = tmp_path_factory.mktemp("fonts") / "cache.json"
    return FontCatalog([Path("/usr/share/fonts"), Path("/usr/local/share/fonts")], cache)


def _edit_first_span(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog, text: str) -> textedit.EditReport:
    span = spans(page)[0]
    return textedit.edit_span(doc, page, catalog, textedit.SpanEdit(
        tuple(span["bbox"]), tuple(span["origin"]), span["text"], text))


def _tagged_fonts(doc: fitz.Document) -> list[int]:
    return [x for x in range(1, doc.xref_length()) if pdfobj.get_key(doc, x, fontres.TAG_KEY)[0] != "null"]


def _program(doc: fitz.Document, xref: int) -> TTFont:
    return TTFont(io.BytesIO(doc.extract_font(xref)[3]))


def _drawn_glyphs(font: TTFont) -> set[int]:
    order = font.getGlyphOrder()
    if "glyf" in font:
        glyf = font["glyf"]
        return {gid for gid, name in enumerate(order) if gid and glyf[name].numberOfContours != 0}
    strings = font["CFF "].cff.topDictIndex[0].CharStrings
    drawn = set()
    for gid, name in enumerate(order):
        strings[name].decompile()
        if gid and len(strings[name].program) > 1:
            drawn.add(gid)
    return drawn


def _gid(doc: fitz.Document, xref: int, char: str) -> int:
    reverse = fontres.analyze_font(doc, xref, verify=False).reverse
    return int.from_bytes(reverse[char], "big")


def test_fallback_face_is_embedded_as_a_subset(catalog):
    doc, page = raw_page(HELVETICA, HELLO)
    before = len(serialize(doc))
    report = _edit_first_span(doc, page, catalog, "Hello Ωmega")
    assert not report.missing_chars
    assert page.get_text().strip() == "Hello Ωmega"
    assert len(serialize(doc)) - before < MAX_GROWTH

    (xref,) = _tagged_fonts(doc)
    font = _program(doc, xref)
    omega = _gid(doc, xref, "Ω")
    assert omega in _drawn_glyphs(font)
    assert len(_drawn_glyphs(font)) <= 2  # "Ω" (and at most one more) - not the whole font
    widths = fontres.analyze_font(doc, xref).widths
    assert set(widths) == {omega.to_bytes(2, "big")}


def test_later_edits_grow_the_subset_and_keep_earlier_glyphs(catalog):
    doc, page = raw_page(HELVETICA, HELLO)
    _edit_first_span(doc, page, catalog, "Hello Ωmega")
    reopened = fitz.open("pdf", serialize(doc))
    page = reopened[0]
    (first,) = _tagged_fonts(reopened)
    face_id = pdfobj.get_key(reopened, first, fontres.TAG_KEY)[1].strip("()")
    style = textedit.StyleRequest(font=f"face:{face_id}", size=24)
    report = textedit.add_text(reopened, page, catalog, textedit.NewText(72, 500, "Ψ and Ω", style))
    assert not report.missing_chars

    (xref,) = _tagged_fonts(reopened)  # one font object per face, shared by both edits
    font = _program(reopened, xref)
    drawn = _drawn_glyphs(font)
    assert {_gid(reopened, xref, "Ω"), _gid(reopened, xref, "Ψ")} <= drawn
    text = reopened[0].get_text()
    assert "Hello Ωmega" in text and "Ψ and Ω" in text

    final = fitz.open("pdf", serialize(reopened))
    assert "Hello Ωmega" in final[0].get_text()
    pix = final[0].get_pixmap(clip=fitz.Rect(72, 495, 200, 530), dpi=72)
    assert pix.color_count() > 1  # the new line is really drawn, not blank


def test_export_with_subsetting_keeps_fallback_text(catalog):
    doc, page = raw_page(HELVETICA, HELLO)
    _edit_first_span(doc, page, catalog, "Hello Ωmega")
    exported = fitz.open("pdf", doctools.export_pdf(serialize(doc), doctools.ExportOptions()))
    assert exported[0].get_text().strip() == "Hello Ωmega"


def test_cjk_fallback_is_embedded_as_a_subset(catalog):
    doc, page = raw_page(HELVETICA, HELLO)
    before = len(serialize(doc))
    report = _edit_first_span(doc, page, catalog, "Hello 中文")
    if report.missing_chars:
        pytest.skip("no installed CJK font")
    assert page.get_text().strip() == "Hello 中文"
    final = fitz.open("pdf", serialize(doc))
    assert final[0].get_text().strip() == "Hello 中文"
    cjk = next(s for s in spans(final[0]) if "中" in s["text"])
    assert final[0].get_pixmap(clip=fitz.Rect(cjk["bbox"]), dpi=72).color_count() > 1  # glyphs are drawn
    # A whole Noto Sans CJK face is ~16 MB.
    assert len(serialize(doc)) - before < 1_000_000


def test_tagged_font_is_found_again():
    doc = fitz.open()
    doc.new_page()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<</Type/Font>>")
    fontres.tag_font(doc, xref, "58adf1c492b3")
    reopened = fitz.open("pdf", doc.tobytes())
    assert fontres.find_tagged_font(reopened, "58adf1c492b3") == xref
    assert fontres.find_tagged_font(reopened, "58adf1c492b3", hint=xref) == xref
    assert fontres.find_tagged_font(reopened, "000000000000") is None
