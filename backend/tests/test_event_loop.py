"""Uploads must never run blocking PDF work on the event-loop thread.

The six upload endpoints are ``async`` (they await the request body). If the PDF
work that follows runs on the loop thread, a held ``PDF_LOCK`` freezes the whole
server, including ``/api/health``, and the Docker health check kills the container.
"""

from __future__ import annotations

import threading
import time

import pymupdf as fitz
import pytest

from app import deps
from app.storage import PDF_LOCK

HEALTH_TIMEOUT = 3.0  # a healthy loop answers in milliseconds


def _png() -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), 0)
    pix.set_rect(pix.irect, (255, 0, 0))
    return pix.tobytes("png")


def _ttf() -> bytes:
    from conftest import find_font

    with open(find_font("LiberationSans-Regular.ttf"), "rb") as handle:
        return handle.read()


def _in_thread(call):
    """Run ``call`` in a daemon thread; ``outcome['response']`` is set when it finishes."""
    outcome: dict = {}
    done = threading.Event()

    def run() -> None:
        try:
            outcome["response"] = call()
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
            outcome["error"] = exc
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()
    return outcome, done


def _assert_loop_is_responsive(client) -> None:
    outcome, done = _in_thread(lambda: client.get("/api/health"))
    assert done.wait(HEALTH_TIMEOUT), "the event loop is blocked: /api/health did not answer"
    assert outcome["response"].status_code == 200


@pytest.fixture()
def with_image(client, doc) -> tuple[str, int]:
    """A document that already holds one image (for the replace endpoint)."""
    doc_id = doc["id"]
    response = client.post(f"/api/documents/{doc_id}/images", data={"page": "0", "rect": "100,600,200,650"},
                           files={"file": ("a.png", _png(), "image/png")})
    assert response.status_code == 200, response.text
    images = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]["images"]
    return doc_id, images[0]["xref"]


PDF_ENDPOINTS = {
    "upload": lambda c, doc_id, xref, pdf: c.post(
        "/api/documents", files={"file": ("x.pdf", pdf, "application/pdf")}),
    "insert_file": lambda c, doc_id, xref, pdf: c.post(
        f"/api/documents/{doc_id}/pages/insert-file", data={"at": "1"},
        files={"file": ("x.pdf", pdf, "application/pdf")}),
    "add_image": lambda c, doc_id, xref, pdf: c.post(
        f"/api/documents/{doc_id}/images", data={"page": "0", "rect": "100,300,200,350"},
        files={"file": ("a.png", _png(), "image/png")}),
    "replace_image": lambda c, doc_id, xref, pdf: c.post(
        f"/api/documents/{doc_id}/images/0/{xref}/replace", files={"file": ("b.png", _png(), "image/png")}),
    "image_watermark": lambda c, doc_id, xref, pdf: c.post(
        f"/api/documents/{doc_id}/watermark/image", data={"opacity": "0.2"},
        files={"file": ("w.png", _png(), "image/png")}),
}


@pytest.mark.parametrize("name", sorted(PDF_ENDPOINTS))
def test_pdf_uploads_do_not_block_the_event_loop(client, with_image, sample_pdf, name):
    doc_id, xref = with_image
    call = PDF_ENDPOINTS[name]
    PDF_LOCK.acquire()  # simulate a long OCR job / another request holding the global lock
    try:
        outcome, done = _in_thread(lambda: call(client, doc_id, xref, sample_pdf))
        time.sleep(0.3)  # let the handler reach the lock
        _assert_loop_is_responsive(client)
        assert not done.is_set(), "the upload should still be waiting for the PDF lock"
    finally:
        PDF_LOCK.release()
    assert done.wait(30), "the upload never finished after the lock was released"
    assert "error" not in outcome, outcome.get("error")
    assert outcome["response"].status_code == 200, outcome["response"].text


def test_font_upload_does_not_block_the_event_loop(client):
    catalog_lock = deps.catalog()._lock  # held while the catalog scans / registers fonts
    catalog_lock.acquire()
    try:
        outcome, done = _in_thread(lambda: client.post("/api/fonts", files={"file": ("copy.ttf", _ttf(), "font/ttf")}))
        time.sleep(0.3)
        _assert_loop_is_responsive(client)
        assert not done.is_set(), "the upload should still be waiting for the catalog lock"
    finally:
        catalog_lock.release()
    assert done.wait(30), "the font upload never finished after the lock was released"
    assert "error" not in outcome, outcome.get("error")
    assert outcome["response"].status_code == 200, outcome["response"].text
