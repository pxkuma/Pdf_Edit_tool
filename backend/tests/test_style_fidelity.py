"""Edited text must reproduce the original text state exactly."""

from __future__ import annotations

import pymupdf as fitz
import pytest

from app.pdf import pdfobj, textstate

STYLED_CONTENT = b"""
q BT /helv 12 Tf 0 0 0 1 k 1 0 0 1 72 700 Tm 80 Tz 1.5 Tc 3 Tw (Scaled spaced text) Tj ET Q
q BT /helv 14 Tf 0.5 g 1 Tr 0.8 w 0 0 1 RG 1 0 0 1 72 670 Tm (Stroked) Tj ET Q
q BT /helv 12 Tf 3 Tr 1 0 0 1 72 640 Tm (Invisible) Tj ET Q
q /GA gs BT /helv 12 Tf 1 0 0 rg 1 0 0.3 1 72 610 Tm (Skewed half) Tj ET Q
q BT /helv 12 Tf 0 0 1 rg 1 0 0 1 72 580 Tm 4 Ts (Raised) Tj ET Q
q BT /helv 12 Tf 2 Tr 1.2 w 0 0.5 0 rg 1 0 0 RG 1 0 0 1 72 550 Tm (FillStroke) Tj ET Q
q 0.5 0 0 0.5 0 0 cm BT /helv 24 Tf 0.2 0.4 0.6 0.1 k 1 0 0 1 144 1000 Tm (Scaled CTM) Tj ET Q
"""


def _styled_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((300, 50), "x", fontname="helv", fontsize=8)  # registers /helv
    pdfobj.add_resource(doc, page, "ExtGState", "GA", "<</Type/ExtGState/ca 0.5/CA 0.5>>")
    pdfobj.append_content(doc, page, STYLED_CONTENT)
    # Text inside a form XObject with its own resources (CMYK + transparency).
    src = fitz.open()
    src_page = src.new_page(width=300, height=100)
    src_page.insert_text((0, 0), "", fontname="helv")
    pdfobj.add_resource(src, src_page, "ExtGState", "GB", "<</Type/ExtGState/ca 0.4>>")
    pdfobj.append_content(src, src_page, b"q /GB gs BT /helv 10 Tf 0 1 1 0 k 1 0 0 1 10 50 Tm (Form text) Tj ET Q")
    page.show_pdf_page(fitz.Rect(72, 420, 372, 520), src, 0)
    return doc.tobytes()


@pytest.fixture()
def styled(client):
    response = client.post("/api/documents", files={"file": ("styled.pdf", _styled_pdf(), "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _spans(client, doc_id):
    model = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]
    return [s for b in model["text"]["blocks"] for line in b["lines"] for s in line["spans"]]


def _records(client, doc_id):
    from app import deps

    pdf = fitz.open(stream=deps.store().current_bytes(doc_id))
    page = pdf[0]
    return pdf, page, textstate.page_text_records(pdf, page)


def _record_for(client, doc_id, needle):
    pdf, page, records = _records(client, doc_id)
    span = next(s for s in _spans(client, doc_id) if needle in s["text"])
    from app.pdf import extract

    for block in extract.page_dict(page)["blocks"]:
        for line in block.get("lines", []):
            for raw in line["spans"]:
                if needle in raw["text"]:
                    return pdf, page, textstate.match_record(records, raw["first_origin"], line["dir"], raw["font"], pdf), span
    raise AssertionError(needle)


def _edit(client, doc_id, needle, new_text, **extra):
    span = next(s for s in _spans(client, doc_id) if needle in s["text"])
    body = {"page": 0, "bbox": span["bbox"], "origin": span["origin"], "original_text": span["text"], "text": new_text}
    body.update(extra)
    response = client.post(f"/api/documents/{doc_id}/text/span", json=body)
    assert response.status_code == 200, response.text
    return span


def _same_state(before, after):
    assert after.render_mode == before.render_mode
    assert after.effective_size == pytest.approx(before.effective_size, abs=0.01)
    assert after.effective_hscale == pytest.approx(before.effective_hscale, abs=0.05)
    assert after.page_char_spacing == pytest.approx(before.page_char_spacing, abs=0.01)
    assert after.page_word_spacing == pytest.approx(before.page_word_spacing, abs=0.01)
    assert after.page_rise == pytest.approx(before.page_rise, abs=0.01)
    assert after.skew == pytest.approx(before.skew, abs=0.005)
    assert after.fill.ops.split()[-1] == before.fill.ops.split()[-1]  # same colour operator / space
    assert after.fill.ops.split()[:-1] == before.fill.ops.split()[:-1] or before.fill.space


@pytest.mark.parametrize("needle,new_text", [
    ("Scaled spaced", "Scaled spaced words"),
    ("Stroked", "Stroked edit"),
    ("Invisible", "Invisible edit"),
    ("Skewed", "Skewed changed"),
    ("Raised", "Raised edit"),
    ("FillStroke", "FillStroke edit"),
    ("Scaled CTM", "Scaled CTM edit"),
])
def test_edit_preserves_exact_state(client, styled, needle, new_text):
    _pdf, _page, before, _span = _record_for(client, styled["id"], needle)
    assert before is not None
    _edit(client, styled["id"], needle, new_text, ocr_mode="hidden")
    _pdf2, page2, after, _span2 = _record_for(client, styled["id"], new_text)
    assert after is not None
    _same_state(before, after)
    if before.render_mode in (1, 2):
        assert after.line_width == pytest.approx(before.line_width, abs=0.01)
        assert after.stroke.ops == before.stroke.ops


def test_cmyk_colour_is_not_converted(client, styled):
    _edit(client, styled["id"], "Scaled spaced", "Still CMYK")
    _pdf, _page, after, span = _record_for(client, styled["id"], "Still CMYK")
    assert after.fill.ops == "0 0 0 1 k"
    assert span["colorSpace"] == "CMYK"


def test_transparency_is_kept(client, styled):
    _edit(client, styled["id"], "Skewed", "Still half")
    pdf, page, after, span = _record_for(client, styled["id"], "Still half")
    assert textstate.fill_opacity(pdf, page, after) == pytest.approx(0.5)
    assert span["opacity"] == pytest.approx(0.5)


def test_model_reports_exact_values(client, styled):
    spans = {s["text"].strip(): s for s in _spans(client, styled["id"])}
    scaled = spans["Scaled spaced text"]
    assert scaled["exact"] is True
    assert scaled["size"] == 12
    assert scaled["hscale"] == pytest.approx(80)
    assert scaled["charSpacing"] == pytest.approx(1.5)
    assert scaled["wordSpacing"] == pytest.approx(3)
    assert spans["Stroked"]["render"] == "stroke"
    assert spans["Invisible"]["render"] == "invisible"
    assert spans["Raised"]["rise"] == pytest.approx(4)
    assert spans["Scaled CTM"]["size"] == pytest.approx(12)


def test_text_inside_form_xobject(client, styled):
    pdf, page, before, _span = _record_for(client, styled["id"], "Form text")
    assert before.fill.ops == "0 1 1 0 k"
    assert textstate.fill_opacity(pdf, page, before) == pytest.approx(0.4)
    _edit(client, styled["id"], "Form text", "Form edited")
    pdf2, page2, after, _ = _record_for(client, styled["id"], "Form edited")
    assert after.fill.ops == "0 1 1 0 k"
    assert textstate.fill_opacity(pdf2, page2, after) == pytest.approx(0.4)
    assert after.effective_size == pytest.approx(before.effective_size, abs=0.01)
    assert "Form text" not in page2.get_text()


def test_user_overrides_apply_on_top_of_exact_state(client, styled):
    _edit(client, styled["id"], "Scaled spaced", "Recoloured", style={"color": "#ff0000", "opacity": 0.3})
    pdf, page, after, _ = _record_for(client, styled["id"], "Recoloured")
    assert after.fill.ops == "1 0 0 rg"
    assert textstate.fill_opacity(pdf, page, after) == pytest.approx(0.3)
    assert after.effective_hscale == pytest.approx(80, abs=0.05)  # untouched properties stay exact
