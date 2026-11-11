"""Consistent document info and storage / page-operation edge cases."""

from __future__ import annotations

import threading

import pymupdf as fitz
import pytest

from app import deps
from app.api import common
from app.jobs import Job
from app.storage import InvalidDocument, _load_any
from conftest import current_pdf, make_sample_pdf


def open_doc(client, payload: bytes, name: str = "t.pdf") -> dict:
    response = client.post("/api/documents", files={"file": (name, payload, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ------------------------------------------------------------------ D7: document info is one snapshot
def test_doc_info_describes_a_single_version(client):
    created = open_doc(client, make_sample_pdf())
    store = deps.store()
    stale = store.get(created["id"])
    client.post(f"/api/documents/{created['id']}/pages/delete", json={"pages": [1]})  # another tab changes the document
    latest = store.get(created["id"])

    info = common.doc_info(stale)

    assert info["version"] == latest.current.file and info["cursor"] == latest.cursor
    assert [page["token"] for page in info["pages"]] == list(latest.current.tokens)
    assert len(info["pages"]) == current_pdf(client, created["id"]).page_count == 1


# ------------------------------------------------------------------ D10: storage and page operations
def test_concurrent_undo_steps_back_once_per_call(client):
    created = open_doc(client, make_sample_pdf())
    doc_id = created["id"]
    for _ in range(4):
        client.post(f"/api/documents/{doc_id}/pages/rotate", json={"pages": [0], "angle": 90})
    store = deps.store()
    assert store.get(doc_id).cursor == 4
    barrier = threading.Barrier(4)

    def undo() -> None:
        barrier.wait()
        store.undo(doc_id)

    threads = [threading.Thread(target=undo) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert store.get(doc_id).cursor == 0  # four undos from cursor 4, none lost to a race


def test_undo_and_redo_hold_the_lock_while_reading_the_cursor(client):
    """The read of the cursor and the jump must be one critical section."""
    created = open_doc(client, make_sample_pdf())
    client.post(f"/api/documents/{created['id']}/pages/rotate", json={"pages": [0], "angle": 90})
    store = deps.store()
    seen = []
    original = store.get

    def spying_get(doc_id):
        from app.storage import PDF_LOCK

        seen.append(PDF_LOCK._is_owned())  # RLock: True only for the owning thread
        return original(doc_id)

    store.get = spying_get
    try:
        store.undo(created["id"])
        store.redo(created["id"])
    finally:
        del store.get
    assert seen and all(seen)


def test_failed_conversion_closes_the_opened_image(monkeypatch):
    closed = []
    real_close = fitz.Document.close

    def counting_close(self, *args, **kwargs):
        closed.append(1)
        return real_close(self, *args, **kwargs)

    def broken_conversion(self, *args, **kwargs):
        raise RuntimeError("cannot convert")

    monkeypatch.setattr(fitz.Document, "close", counting_close)
    monkeypatch.setattr(fitz.Document, "convert_to_pdf", broken_conversion)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), 0)
    with pytest.raises(InvalidDocument):
        _load_any(pix.tobytes("png"), None)
    assert closed, "the half-opened image document must be closed on the error path"


def test_unreadable_inserted_image_is_a_clean_error(client):
    created = open_doc(client, make_sample_pdf())
    response = client.post(f"/api/documents/{created['id']}/pages/insert-file", data={"at": "0"},
                           files={"file": ("x.png", b"not really an image", "image/png")})
    assert response.status_code == 400


def test_reordering_with_repeats_makes_independent_pages(client):
    created = open_doc(client, make_sample_pdf())
    doc_id = created["id"]
    response = client.post(f"/api/documents/{doc_id}/pages/reorder", json={"order": [0, 0, 1]})
    assert response.status_code == 200, response.text
    pdf = current_pdf(client, doc_id)
    assert pdf.page_count == 3
    assert len({pdf.page_xref(i) for i in range(3)}) == 3  # no page object is used twice
    assert "Invoice" in pdf[0].get_text() and "Invoice" in pdf[1].get_text()
    # Erase the title on the second copy only.
    client.post(f"/api/documents/{doc_id}/redact", json={"page": 1, "rects": [[60, 70, 400, 110]], "mode": "text"})
    pdf = current_pdf(client, doc_id)
    assert "Invoice" in pdf[0].get_text() and "Invoice" not in pdf[1].get_text()


def test_reorder_keeps_plain_permutations_unchanged(client):
    created = open_doc(client, make_sample_pdf())
    client.post(f"/api/documents/{created['id']}/pages/reorder", json={"order": [1, 0]})
    pdf = current_pdf(client, created["id"])
    assert "Second page" in pdf[0].get_text() and "Invoice" in pdf[1].get_text()


def test_job_progress_counts_every_page_from_many_threads():
    job = Job("j", "d", "ocr", total=800)

    def work() -> None:
        for _ in range(100):
            job.advance("page")

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert job.done == 800


# ------------------------------------------------------------------ D8: page model of the requested revision
def test_page_model_names_its_revision_and_refuses_another(client):
    created = open_doc(client, make_sample_pdf())
    doc_id, token = created["id"], created["pages"][0]["token"]
    ok = client.get(f"/api/documents/{doc_id}/pages/0/model", params={"t": token})
    assert ok.status_code == 200 and ok.json()["data"]["token"] == token
    stale = client.get(f"/api/documents/{doc_id}/pages/0/model", params={"t": "0" * 12})
    assert stale.status_code == 409
    assert client.get(f"/api/documents/{doc_id}/pages/0/model").status_code == 200  # the token stays optional
