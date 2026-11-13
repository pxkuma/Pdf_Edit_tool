"""Characters outside the BMP in ToUnicode CMaps (audit C5)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fontkit import raw_page, spans

from app.pdf import cmap, pdfobj, textedit
from app.pdf.fonts import FontCatalog

HELLO = b"BT /F1 24 Tf 72 700 Td (Hello World) Tj ET"
GRIN = "\U0001F600"


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> FontCatalog:
    cache = tmp_path_factory.mktemp("fonts") / "cache.json"
    return FontCatalog([Path("/usr/share/fonts"), Path("/usr/local/share/fonts")], cache)


def _cmap(body: str) -> str:
    return f"begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange {body} endcmap"


def test_surrogate_pairs_are_decoded():
    parsed = cmap.parse_tounicode(_cmap("1 beginbfchar <0001> <D83DDE00> endbfchar"))
    assert parsed == {b"\x00\x01": GRIN}


def test_code_point_destinations_from_broken_producers_are_decoded():
    # MuPDF 1.28 writes non-BMP destinations as bare (odd-length) code points.
    text = _cmap("1 beginbfrange <16e1> <16e3> <1f600> endbfrange 1 beginbfchar <1720> <1f643> endbfchar")
    parsed = cmap.parse_tounicode(text)
    assert parsed[b"\x16\xe1"] == GRIN
    assert parsed[b"\x16\xe3"] == "\U0001F602"
    assert parsed[b"\x17\x20"] == "\U0001F643"


def test_built_cmap_round_trips_with_surrogates():
    mapping = {
        b"\x00\x03": " ", b"\x00\x04": "!", b"\x00\x05": '"',  # a range
        b"\x00\x10": GRIN, b"\x00\x11": "\U0001F601",
        b"\x00\x20": "ffi", b"\x01\x00": "中",
    }
    text = cmap.build_tounicode(mapping, 2)
    assert cmap.parse_tounicode(text) == mapping
    assert cmap.code_width(text) == 2
    assert not [h for h in re.findall(r"<([0-9A-Fa-f]+)>", text) if len(h) % 4]


def test_edit_with_emoji_reads_back_exactly(catalog):
    doc, page = raw_page("<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>", HELLO)
    span = spans(page)[0]
    text = f"Hello Ωmega {GRIN}"
    report = textedit.edit_span(doc, page, catalog, textedit.SpanEdit(
        tuple(span["bbox"]), tuple(span["origin"]), span["text"], text))
    if report.missing_chars:
        pytest.skip(f"no installed font draws {report.missing_chars}")
    assert page.get_text().strip() == text
    for font in page.get_fonts(full=True):
        kind, value = pdfobj.get_key(doc, font[0], "ToUnicode")
        if kind == "xref":
            stream = pdfobj.stream_text(doc, pdfobj.ref_xref(value))
            assert not [h for h in re.findall(r"<([0-9A-Fa-f]+)>", stream) if len(h) % 2]
