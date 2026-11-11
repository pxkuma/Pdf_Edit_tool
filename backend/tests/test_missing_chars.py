"""Characters that no installed font can draw are reported by every tool that writes text, not dropped silently."""

from __future__ import annotations

import time

import pymupdf as fitz
import pytest

from app import deps
from app.pdf import ocr
from conftest import make_sample_pdf

UNDRAWABLE = ""  # a private-use code point: no installed font has a glyph for it


@pytest.fixture()
def doc(client) -> dict:
    response = client.post("/api/documents", files={"file": ("t.pdf", make_sample_pdf(), "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def post(client, doc: dict, route: str, body: dict) -> dict:
    response = client.post(f"/api/documents/{doc['id']}/{route}", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]["result"]


STYLE = {"font": "", "size": 24, "color": "#336699", "opacity": 0.5, "bold": False, "italic": False}


# ------------------------------------------------------------------ watermark
@pytest.mark.parametrize("layout", ["center", "tile"])
def test_text_watermark_reports_characters_it_could_not_draw(client, doc, layout):
    result = post(client, doc, "watermark", {"text": f"DRAFT {UNDRAWABLE}", "layout": layout, "angle": 30, "style": STYLE})
    assert result == {"missing_chars": [UNDRAWABLE]}


def test_text_watermark_without_missing_characters_reports_none(client, doc):
    result = post(client, doc, "watermark", {"text": "DRAFT", "layout": "center", "angle": 0, "style": STYLE})
    assert result == {"missing_chars": []}


def test_watermark_still_writes_the_drawable_characters(client, doc):
    post(client, doc, "watermark", {"text": f"DRAFTCOPY{UNDRAWABLE}", "layout": "center", "angle": 0, "style": STYLE})
    text = fitz.open(stream=deps.store().current_bytes(doc["id"]))[0].get_text()
    assert "DRAFTCOPY" in text and UNDRAWABLE not in text


# ------------------------------------------------------------------ header and footer
def test_header_footer_reports_characters_it_could_not_draw(client, doc):
    body = {"template": f"Page {{n}} {UNDRAWABLE}", "position": "bottom-center", "margin": 28, "start_number": 1,
            "style": STYLE}
    assert post(client, doc, "header-footer", body) == {"missing_chars": [UNDRAWABLE]}


def test_header_footer_without_missing_characters_reports_none(client, doc):
    body = {"template": "Page {n} of {total}", "position": "top-right", "margin": 28, "start_number": 1, "style": STYLE}
    assert post(client, doc, "header-footer", body) == {"missing_chars": []}


# ------------------------------------------------------------------ OCR
def _line(text: str) -> ocr.OcrLine:
    word = ocr.OcrWord(text, (72, 100, 72 + 12 * len(text), 120), 90.0)
    return ocr.OcrLine([word], word.rect)


def test_text_layer_reports_characters_it_could_not_draw(client):
    pdf = fitz.open()
    page = pdf.new_page()
    layer = ocr.write_text_layer(pdf, page, deps.catalog(), [_line(f"Invoice{UNDRAWABLE}"), _line("Total")])
    assert layer.words == 2
    assert layer.missing_chars == [UNDRAWABLE]
    assert "Invoice" in page.get_text() and "Total" in page.get_text()


def test_text_layer_without_missing_characters_reports_none(client):
    pdf = fitz.open()
    layer = ocr.write_text_layer(pdf, pdf.new_page(), deps.catalog(), [_line("Invoice")])
    assert (layer.words, layer.missing_chars) == (1, [])


def _tsv(*words: str) -> str:
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    line = "4\t1\t1\t1\t1\t0\t100\t100\t800\t50\t-1\t"
    rows = [f"5\t1\t1\t1\t1\t{i}\t{100 + 200 * i}\t100\t150\t50\t90\t{word}" for i, word in enumerate(words, 1)]
    return "\n".join([header, line, *rows]) + "\n"


def _wait(client, job_id: str, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()["data"]
        if job["status"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("OCR job did not finish")


def test_ocr_job_result_carries_the_missing_characters(client, doc, monkeypatch):
    monkeypatch.setattr(ocr, "languages", lambda: ("eng",))
    monkeypatch.setattr(ocr, "run_tesseract", lambda png, language, dpi: _tsv(f"Total{UNDRAWABLE}", "due"))
    job = client.post(f"/api/documents/{doc['id']}/ocr", json={"language": "eng", "pages": "1", "force": True})
    assert job.status_code == 200, job.text
    finished = _wait(client, job.json()["data"]["id"])
    assert finished["status"] == "done", finished
    assert finished["result"]["pages"] == [0] and finished["result"]["words"] == 2
    assert finished["result"]["missing_chars"] == [UNDRAWABLE]


def test_ocr_job_without_pages_to_do_reports_no_missing_characters(client, doc, monkeypatch):
    monkeypatch.setattr(ocr, "languages", lambda: ("eng",))
    monkeypatch.setattr(ocr, "page_scan_info", lambda page: {"hasOcr": True})
    job = client.post(f"/api/documents/{doc['id']}/ocr", json={"language": "eng"}).json()["data"]
    finished = _wait(client, job["id"])
    assert finished["result"] == {"pages": [], "words": 0, "skipped": [], "missing_chars": []}
