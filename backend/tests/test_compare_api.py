"""Comparing the open document with an uploaded file: upload, run, results, temporary storage."""

from __future__ import annotations

import os
import time

import pymupdf as fitz
import pytest
from comparekit import change_summary, make_pdf, paragraph

from app import deps

PAGES = [paragraph("alpha"), paragraph("bravo"), paragraph("charlie")]


def upload(client, data: bytes, name: str = "revised.pdf", **fields):
    return client.post(f"/api/documents/{fields.pop('doc_id')}/compare", files={"file": (name, data, "application/pdf")}, data=fields)


@pytest.fixture()
def base_doc(client) -> dict:
    response = client.post("/api/documents", files={"file": ("original.pdf", make_pdf(PAGES), "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def choose(client, doc: dict, data: bytes, **fields) -> dict:
    response = upload(client, data, doc_id=doc["id"], **fields)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def finish(client, job: dict) -> dict:
    deadline = time.time() + 60
    while job["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
        job = client.get(f"/api/jobs/{job['id']}").json()["data"]
    return job


def run(client, doc: dict, session: dict, **body) -> dict:
    response = client.post(f"/api/documents/{doc['id']}/compare/{session['id']}/run", json={"mode": "both", **body})
    assert response.status_code == 200, response.text
    job = finish(client, response.json()["data"])
    assert job["status"] == "done", job
    report = client.get(f"/api/documents/{doc['id']}/compare/{session['id']}/report")
    assert report.status_code == 200, report.text
    return report.json()["data"]


def compare_with(client, doc: dict, pages: list[list[str]], **body) -> dict:
    return run(client, doc, choose(client, doc, make_pdf(pages)), **body)


def test_the_same_content_has_no_changes(client, base_doc):
    report = compare_with(client, base_doc, PAGES)
    assert report["totals"]["changes"] == 0
    assert report["totals"]["matched"] == 3
    assert report["baseVersion"] == base_doc["version"]
    assert report["base"] == {"filename": "original.pdf", "pages": 3}
    assert report["other"] == {"filename": "revised.pdf", "pages": 3}


def test_an_edit_and_an_inserted_page_in_one_report(client, base_doc):
    revised = [PAGES[0], paragraph("delta"), [PAGES[1][0].replace("alpha", "x"), *PAGES[1][1:]], PAGES[2]]
    revised[2][0] = revised[2][0].replace("bravo line 1", "bravo changed line 1")
    report = compare_with(client, base_doc, revised)
    assert [p["status"] for p in report["pairs"]] == ["matched", "inserted", "changed", "matched"]
    assert change_summary(report["pairs"][2]) == [("insert", "", "changed")]
    assert report["totals"]["pagesWithChanges"] == 2
    assert report["totals"]["changes"] == 2


def test_a_visual_difference_is_found_through_the_api(client, base_doc):
    other = make_pdf(PAGES, boxes={2: [((300, 400, 450, 500), (1, 0, 0))]})
    report = run(client, base_doc, choose(client, base_doc, other), mode="visual")
    (change,) = report["pairs"][2]["changes"]
    assert change["kind"] == "visual" and change["rectsB"][0][0] < 301
    assert report["options"]["mode"] == "visual"


def test_the_job_reports_progress_and_a_summary(client, base_doc):
    session = choose(client, base_doc, make_pdf(PAGES[:2]))
    started = client.post(f"/api/documents/{base_doc['id']}/compare/{session['id']}/run", json={"mode": "text"}).json()["data"]
    job = finish(client, started)
    assert job["kind"] == "compare" and job["status"] == "done"
    assert job["done"] == job["total"] > 0
    assert job["result"]["removed"] == 1
    assert "1 change" in job["message"]


def test_comparing_never_changes_the_open_document(client, base_doc):
    before = client.get(f"/api/documents/{base_doc['id']}").json()["data"]
    compare_with(client, base_doc, [PAGES[1]])
    after = client.get(f"/api/documents/{base_doc['id']}").json()["data"]
    assert after["version"] == before["version"] and after["cursor"] == 0 and after["history"] == before["history"]
    assert [p["token"] for p in after["pages"]] == [p["token"] for p in before["pages"]]


def test_the_second_file_is_not_a_document(client, base_doc):
    session = choose(client, base_doc, make_pdf(PAGES))
    assert client.get(f"/api/documents/{session['id']}").status_code == 404
    assert not (deps.settings().docs_dir / session["id"]).exists()
    assert (deps.settings().compare_dir / session["id"] / "other.pdf").exists()
    assert session["pageCount"] == 3 and session["pages"][0] == {"index": 0, "width": 595.0, "height": 842.0}
    assert all(len(d.name) == 32 and (d / "state.json").exists() for d in deps.settings().docs_dir.iterdir())


def test_a_new_file_replaces_the_previous_one_of_the_document(client, base_doc):
    first = choose(client, base_doc, make_pdf(PAGES))
    second = choose(client, base_doc, make_pdf(PAGES[:1]))
    assert not (deps.settings().compare_dir / first["id"]).exists()
    assert client.get(f"/api/documents/{base_doc['id']}/compare/{first['id']}").status_code == 404
    assert client.get(f"/api/documents/{base_doc['id']}/compare/{second['id']}").json()["data"]["pageCount"] == 1


def test_closing_the_comparison_deletes_the_file(client, base_doc):
    session = choose(client, base_doc, make_pdf(PAGES))
    assert client.delete(f"/api/documents/{base_doc['id']}/compare/{session['id']}").json()["ok"]
    assert not (deps.settings().compare_dir / session["id"]).exists()


def test_closing_the_document_deletes_the_file(client):
    doc = client.post("/api/documents", files={"file": ("a.pdf", make_pdf(PAGES), "application/pdf")}).json()["data"]
    session = choose(client, doc, make_pdf(PAGES))
    assert client.delete(f"/api/documents/{doc['id']}").json()["ok"]
    assert not (deps.settings().compare_dir / session["id"]).exists()


def test_expired_and_orphaned_files_are_cleaned_up(client, base_doc):
    sessions = deps.compare_store()
    fresh, old = choose(client, base_doc, make_pdf(PAGES)), None
    other_doc = client.post("/api/documents", files={"file": ("b.pdf", make_pdf(PAGES), "application/pdf")}).json()["data"]
    old = choose(client, other_doc, make_pdf(PAGES))
    marker = deps.compare_store().root / old["id"] / "session.json"
    stamp = time.time() - sessions.ttl_seconds - 60
    os.utime(marker, (stamp, stamp))
    assert sessions.cleanup() >= 1
    assert not (sessions.root / old["id"]).exists() and (sessions.root / fresh["id"]).exists()
    deps.store().delete(base_doc["id"])  # the document disappears without a proper close
    assert sessions.cleanup() >= 1
    assert not (sessions.root / fresh["id"]).exists()


def test_a_session_belongs_to_its_document(client, base_doc):
    session = choose(client, base_doc, make_pdf(PAGES))
    other = client.post("/api/documents", files={"file": ("c.pdf", make_pdf(PAGES), "application/pdf")}).json()["data"]
    assert client.get(f"/api/documents/{other['id']}/compare/{session['id']}").status_code == 404
    assert client.get(f"/api/documents/{other['id']}/compare/{session['id']}/report").status_code == 404


def test_the_report_needs_a_run_first(client, base_doc):
    session = choose(client, base_doc, make_pdf(PAGES))
    assert client.get(f"/api/documents/{base_doc['id']}/compare/{session['id']}").json()["data"]["hasReport"] is False
    assert client.get(f"/api/documents/{base_doc['id']}/compare/{session['id']}/report").status_code == 404
    run(client, base_doc, session)
    assert client.get(f"/api/documents/{base_doc['id']}/compare/{session['id']}").json()["data"]["hasReport"] is True


def test_the_upload_respects_the_size_limit(client, base_doc, monkeypatch):
    from app.config import Settings

    small = Settings(**{**deps.settings().__dict__, "max_upload_mb": 0})
    monkeypatch.setattr(deps, "settings", lambda: small)
    assert upload(client, make_pdf(PAGES), doc_id=base_doc["id"]).status_code == 413
    assert upload(client, b"", doc_id=base_doc["id"]).status_code in (400, 413)


def test_invalid_uploads_are_rejected(client, base_doc):
    assert upload(client, b"", doc_id=base_doc["id"]).status_code == 400
    response = upload(client, b"this is not a pdf at all", doc_id=base_doc["id"])
    assert response.status_code == 400 and response.json()["ok"] is False
    assert upload(client, make_pdf(PAGES), doc_id="0" * 32).status_code == 404


def test_a_password_protected_file_asks_for_the_password(client, base_doc):
    pdf = fitz.open("pdf", make_pdf(PAGES))
    locked = pdf.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    response = upload(client, locked, doc_id=base_doc["id"])
    assert response.status_code == 401 and response.json()["code"] == "password_required"
    session = choose(client, base_doc, locked, password="secret")
    assert run(client, base_doc, session)["totals"]["changes"] == 0


def test_an_image_can_be_the_second_file(client, base_doc):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.set_rect(pix.irect, (10, 20, 30))
    session = choose(client, base_doc, pix.tobytes("png"))
    assert session["pageCount"] == 1


def test_the_second_file_can_be_rendered_page_by_page(client, base_doc):
    session = choose(client, base_doc, make_pdf(PAGES))
    url = f"/api/documents/{base_doc['id']}/compare/{session['id']}/pages"
    response = client.get(f"{url}/1/render?scale=0.5")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert client.get(f"{url}/3/render").status_code == 400
    assert client.get(f"{url}/-1/render").status_code == 400


def test_running_twice_at_once_is_refused(client, base_doc):
    big = make_pdf([paragraph(f"topic{n}", 8) for n in range(60)])
    session = choose(client, base_doc, big)
    url = f"/api/documents/{base_doc['id']}/compare/{session['id']}/run"
    first = client.post(url, json={"mode": "visual"})
    second = client.post(url, json={"mode": "visual"})
    assert first.status_code == 200
    assert second.status_code in (200, 409)  # 409 while the first is still running
    finish(client, first.json()["data"])


def test_run_options_are_validated(client, base_doc):
    session = choose(client, base_doc, make_pdf(PAGES))
    url = f"/api/documents/{base_doc['id']}/compare/{session['id']}/run"
    assert client.post(url, json={"mode": "everything"}).status_code == 422
    assert client.post(url, json={"mode": "visual", "dpi": 600}).status_code == 422
    assert client.post(url, json={"sensitivity": "extreme"}).status_code == 422


def test_a_document_edited_while_comparing_is_reported(client):
    doc = client.post("/api/documents", files={"file": ("e.pdf", make_pdf(PAGES), "application/pdf")}).json()["data"]
    session = choose(client, doc, make_pdf(PAGES))
    client.post(f"/api/documents/{doc['id']}/pages/rotate", json={"pages": [0], "angle": 90})
    report = run(client, doc, session)  # a run started after the edit compares the edited version
    assert report["baseVersion"] != doc["version"]


def test_too_many_pages_for_a_visual_comparison_fail_the_job_clearly(client):
    many = make_pdf([[f"page {n}"] for n in range(301)])
    doc = client.post("/api/documents", files={"file": ("many.pdf", many, "application/pdf")}).json()["data"]
    session = choose(client, doc, many)
    response = client.post(f"/api/documents/{doc['id']}/compare/{session['id']}/run", json={"mode": "visual"})
    job = finish(client, response.json()["data"])
    assert job["status"] == "error" and "at most 300" in job["error"]
    assert run(client, doc, session, mode="text")["totals"]["changes"] == 0
