"""Simple-font encodings (audit C1): typed characters must map to the right codes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fontkit import add_stream, raw_page, spans

from app.pdf import cmap, encodings, fontres, textedit
from app.pdf.fonts import FontCatalog

HELLO = b"BT /F1 24 Tf 72 700 Td (Hello World) Tj ET"


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> FontCatalog:
    cache = tmp_path_factory.mktemp("fonts") / "cache.json"
    return FontCatalog([Path("/usr/share/fonts"), Path("/usr/local/share/fonts")], cache)


def _font(doc, page) -> fontres.EmbeddedFont:
    return fontres.analyze_font(doc, page.get_fonts()[0][0])


def test_standard_encoding_is_not_latin1():
    doc, page = raw_page("<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>", HELLO)
    font = _font(doc, page)
    assert font.code_for("'") == b"\xa9"  # quotesingle
    assert font.code_for("’") == b"\x27"  # quoteright
    assert font.code_for("`") == b"\xc1"  # grave
    assert font.code_for("‘") == b"\x60"  # quoteleft
    assert font.code_for("Ø") == b"\xe9"
    assert font.code_for("é") is None  # not in StandardEncoding at all
    assert font.code_for("®") is None


def test_standard14_edit_reads_back_what_was_typed(catalog):
    doc, page = raw_page("<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>", HELLO)
    span = spans(page)[0]
    text = "Café 'quote' `x` ®"
    edit = textedit.SpanEdit(tuple(span["bbox"]), tuple(span["origin"]), span["text"], text)
    report = textedit.edit_span(doc, page, catalog, edit)
    assert page.get_text().strip() == text
    assert report.exact_font is False  # é and ® came from a substitute


def test_differences_use_full_glyph_name_list():
    encoding = "<</Type/Encoding/BaseEncoding/WinAnsiEncoding/Differences[128/Euro/lslash 200/f_i/uni2126]>>"
    doc, page = raw_page(f"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding {encoding}>>", HELLO)
    font = _font(doc, page)
    assert font.code_for("€") == b"\x80"
    assert font.code_for("ł") == b"\x81"
    assert font.code_for("fi") == b"\xc8"
    assert font.code_for("\u2126") == b"\xc9"  # OHM SIGN


def test_differences_without_base_start_from_standard_encoding():
    doc, page = raw_page("<</Type/Font/Subtype/Type1/BaseFont/Times-Roman/Encoding<</Differences[65/B]>>>>", HELLO)
    font = _font(doc, page)
    assert font.code_for("B") == b"\x41"
    assert font.code_for("’") == b"\x27"


def test_pdf_mac_roman_differs_from_python_codec():
    doc, page = raw_page("<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/MacRomanEncoding>>", HELLO)
    font = _font(doc, page)
    assert font.code_for("¤") == b"\xdb"
    assert font.code_for("€") is None
    assert font.code_for("π") is None  # Mac OS Roman 0xB9, absent from PDF MacRomanEncoding
    assert font.code_for("é") == b"\x8e"


def test_symbol_font_never_guesses_latin_codes():
    doc, page = raw_page("<</Type/Font/Subtype/Type1/BaseFont/Symbol>>", HELLO)
    assert _font(doc, page).code_for("a") is None


def test_unknown_base_encoding_is_not_cp1252():
    assert cmap.simple_encoding_map("NoSuchEncoding", None) == {}


def test_pdfdoc_encoding_special_block():
    table = encodings.to_unicode_table(encodings.base_glyph_table("PDFDocEncoding"))
    assert table[0x80] == "•"
    assert table[0xA0] == "€"
    assert table[0xE9] == "é"


def test_embedded_tounicode_still_wins():
    def setup(doc, font_xref):
        stream = add_stream(doc, b"/CIDInit /ProcSet findresource begin 1 begincodespacerange <00> <FF> "
                                 b"endcodespacerange 1 beginbfchar <27> <0027> endbfchar end")
        doc.xref_set_key(font_xref, "ToUnicode", f"{stream} 0 R")

    doc, page = raw_page("<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>", HELLO, (setup,))
    assert _font(doc, page).code_for("'") == b"\x27"
