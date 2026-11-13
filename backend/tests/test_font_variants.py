"""Several codes for one character: keep the variant the text uses (audit C12)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fontkit import add_stream, raw_page, spans, tounicode

from app.pdf import textedit
from app.pdf.fonts import FontCatalog

# Code 0x31 is a lining "1", code 0x81 an old-style "1": both map to U+0031.
PAIRS = {0x20: " ", 0x31: "1", 0x32: "2", 0x81: "1", 0x82: "2"}


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> FontCatalog:
    cache = tmp_path_factory.mktemp("fonts") / "cache.json"
    return FontCatalog([Path("/usr/share/fonts"), Path("/usr/local/share/fonts")], cache)


def _page(content: bytes):
    def setup(doc, font_xref):
        tu = add_stream(doc, tounicode(PAIRS))
        widths = " ".join("500" for _ in range(32, 256))
        doc.update_object(font_xref, f"<</Type/Font/Subtype/TrueType/BaseFont/Test/FirstChar 32/LastChar 255"
                                     f"/Widths[{widths}]/ToUnicode {tu} 0 R>>")
    return raw_page("<<>>", content, (setup,))


def _written_codes(doc, page) -> bytes:
    return doc.xref_stream(page.get_contents()[-1])


@pytest.mark.parametrize(("content", "code"), [
    (b"BT /F1 24 Tf 72 700 Td <8182> Tj ET", b"<81>"),
    (b"BT /F1 24 Tf 72 700 Td <3132> Tj ET", b"<31>"),
])
def test_edit_keeps_the_figure_style_of_the_text(catalog, content, code):
    doc, page = _page(content)
    span = spans(page)[0]
    textedit.edit_span(doc, page, catalog, textedit.SpanEdit(tuple(span["bbox"]), tuple(span["origin"]),
                                                             span["text"], "21"))
    written = _written_codes(doc, page)
    assert code in written
    other = b"<31>" if code == b"<81>" else b"<81>"
    assert other not in written
