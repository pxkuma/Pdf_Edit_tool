"""OCR of scanned pages and editing of recognised text (requires Tesseract)."""

from __future__ import annotations

import time

import pymupdf as fitz
import pytest

from app.pdf import ocr

needs_tesseract = pytest.mark.skipif(not ocr.tesseract_path() or "eng" not in ocr.languages(),
                                     reason="tesseract with English data not installed")


def _scanned_pdf() -> bytes:
    """A page containing only a picture of text, like a scanner produces."""
    src = fitz.open()
    page = src.new_page(width=595, height=842)
    page.insert_text((72, 120), "Scanned Invoice", fontname="hebo", fontsize=28)
    page.insert_text((72, 180), "Customer reference number 4821", fontname="helv", fontsize=16)
    page.insert_text((72, 220), "Payment due within thirty days", fontname="helv", fontsize=16)
    pix = page.get_pixmap(dpi=200)
    out = fitz.open()
    target = out.new_page(width=595, height=842)
    target.insert_image(target.rect, stream=pix.tobytes("png"))
    return out.tobytes()


def _wait(client, job_id: str, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()["data"]
        if job["status"] != "running":
            return job
        time.sleep(0.3)
    raise AssertionError("OCR job did not finish")


@pytest.fixture()
def scanned(client):
    response = client.post("/api/documents", files={"file": ("scan.pdf", _scanned_pdf(), "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_capabilities_endpoint(client):
    data = client.get("/api/ocr").json()["data"]
    assert set(data) == {"available", "languages", "default"}


def test_scanned_page_is_detected(client, scanned):
    model = client.get(f"/api/documents/{scanned['id']}/pages/0/model").json()["data"]
    assert model["scan"] == {"scanned": True, "hasOcr": False}


def test_unknown_language_rejected(client, scanned):
    response = client.post(f"/api/documents/{scanned['id']}/ocr", json={"language": "zzz"})
    assert response.status_code == 400


@needs_tesseract
def test_ocr_makes_scan_searchable_and_editable(client, scanned):
    doc_id = scanned["id"]
    job = client.post(f"/api/documents/{doc_id}/ocr", json={"language": "eng"}).json()["data"]
    job = _wait(client, job["id"])
    assert job["status"] == "done", job
    assert job["result"]["words"] >= 8
    assert job["document"]["canUndo"] is True

    model = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]
    assert model["scan"]["hasOcr"] is True
    words = {w["text"] for w in model["text"]["words"]}
    assert {"Customer", "reference", "Payment"} <= words
    hits = client.get(f"/api/documents/{doc_id}/search", params={"q": "thirty"}).json()["data"]
    assert len(hits) == 1
    spans = [s for b in model["text"]["blocks"] for line in b["lines"] for s in line["spans"]]
    target = next(s for s in spans if "4821" in s["text"])
    assert target["ocr"] is True and target["render"] == "invisible"
    # The invisible word sits over the scanned word.
    hit = client.get(f"/api/documents/{doc_id}/search", params={"q": "4821"}).json()["data"][0]
    assert abs(hit["rect"][0] - target["bbox"][0]) < 2

    # Editing a recognised word replaces it in the image with real, visible text.
    body = {"page": 0, "bbox": target["bbox"], "origin": target["origin"], "original_text": target["text"], "text": "9999"}
    response = client.post(f"/api/documents/{doc_id}/text/span", json=body)
    assert response.status_code == 200, response.text
    from app import deps

    pdf = fitz.open(stream=deps.store().current_bytes(doc_id))
    traces = [t for t in pdf[0].get_texttrace() if "".join(chr(c[0]) for c in t["chars"]) == "9999"]
    assert traces and traces[0]["type"] == 0  # visible
    assert max(traces[0]["color"]) < 0.35  # ink colour sampled from the scan (dark)
    assert "4821" not in pdf[0].get_text()
    # The scanned pixels under the old word were painted over.
    clip = fitz.Rect(target["bbox"])
    assert pdf[0].get_pixmap(clip=clip, dpi=72).color_count() < 400


@needs_tesseract
def test_ocr_skips_pages_already_recognised(client, scanned):
    doc_id = scanned["id"]
    _wait(client, client.post(f"/api/documents/{doc_id}/ocr", json={}).json()["data"]["id"])
    again = _wait(client, client.post(f"/api/documents/{doc_id}/ocr", json={}).json()["data"]["id"])
    assert again["result"]["pages"] == []
    forced = _wait(client, client.post(f"/api/documents/{doc_id}/ocr", json={"force": True}).json()["data"]["id"])
    assert forced["result"]["pages"] == [0]
    from app import deps

    text = fitz.open(stream=deps.store().current_bytes(doc_id))[0].get_text()
    assert text.count("Customer") == 1  # old layer replaced, not duplicated
