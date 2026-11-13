"""Choosing the page font of a span by name (audit C14)."""

from __future__ import annotations

import pymupdf as fitz
import pytest
from fontkit import add_stream, tounicode

from app.pdf import textedit
from app.pdf.fonts import font_name_rank

TEXT = {code: chr(code) for code in range(32, 127)}


def _page_with_fonts(*names: str) -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    page = doc.new_page()
    resources = []
    for index, name in enumerate(names, 1):
        xref = doc.get_new_xref()
        tu = add_stream(doc, tounicode(TEXT))
        doc.update_object(xref, f"<</Type/Font/Subtype/TrueType/BaseFont/{name}/FirstChar 32/LastChar 126"
                                f"/Widths[{' '.join('500' for _ in TEXT)}]/ToUnicode {tu} 0 R>>")
        resources.append(f"/F{index} {xref} 0 R")
    doc.xref_set_key(page.xref, "Resources", f"<</Font<<{''.join(resources)}>>>>")
    reopened = fitz.open("pdf", doc.tobytes())
    return reopened, reopened[0]


def _resolved(names: tuple[str, ...], span_font: str) -> str | None:
    doc, page = _page_with_fonts(*names)
    font = textedit.resolve_span_font(doc, page, {"font": span_font, "text": "Hello"})
    return font.base_name if font is not None else None


def test_exact_name_wins_over_another_weight():
    assert _resolved(("Calibri-Light", "Calibri"), "Calibri") == "Calibri"
    assert _resolved(("Arial-BoldMT", "ArialMT"), "ArialMT") == "ArialMT"


def test_prefix_never_switches_weight_or_slant():
    assert _resolved(("Arial-BoldMT",), "Arial") is None
    assert _resolved(("Calibri-Light",), "Calibri") is None
    assert _resolved(("Arial-ItalicMT",), "ArialMT") is None


def test_prefix_with_only_a_vendor_suffix_still_matches():
    assert _resolved(("ArialMT",), "Arial") == "ArialMT"
    assert _resolved(("TimesNewRomanPSMT",), "TimesNewRoman") == "TimesNewRomanPSMT"


@pytest.mark.parametrize(("wanted", "name", "rank"), [
    ("Arial", "Arial", 0),
    ("ABCDEF+Arial", "Arial", 0),
    ("Arial", "ArialMT", 1),
    ("Arial", "Arial-BoldMT", None),
    ("Arial", "Arimo", None),
    # MuPDF truncates long names: a truncated name is a prefix of the full one.
    ("HelveticaNeueLTStd-BoldCondObli", "HelveticaNeueLTStd-BoldCondOblique", 1),
])
def test_font_name_rank(wanted, name, rank):
    assert font_name_rank(wanted, name) == rank
