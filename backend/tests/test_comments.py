"""Comments: notes and markup with text, reply threads, review status, deletion."""

from __future__ import annotations

import re

import pymupdf as fitz
import pytest

from app.pdf import comments
from app.pdf.pdfdates import format_pdf_date, parse_pdf_date, to_iso
from conftest import current_pdf

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def base(doc: dict) -> str:
    return f"/api/documents/{doc['id']}"


def add(client, doc: dict, **body) -> int:
    body = {"page": 0, "kind": "note", "point": [100, 200], "text": "Look here", "author": "Alice", **body}
    response = client.post(f"{base(doc)}/comments", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]["result"]["xref"]


def reply(client, doc: dict, parent: int, text: str = "I agree", author: str = "Bob", page: int = 0) -> int:
    response = client.post(f"{base(doc)}/comments/{page}/{parent}/replies", json={"text": text, "author": author})
    assert response.status_code == 200, response.text
    return response.json()["data"]["result"]["xref"]


def listing(client, doc: dict) -> dict:
    response = client.get(f"{base(doc)}/comments")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def by_xref(data: dict, xref: int) -> dict:
    for comment in data["comments"]:
        if comment["xref"] == xref:
            return comment
    raise AssertionError(f"comment {xref} not listed")


def render(client, doc_id: str) -> bytes:
    info = client.get(f"/api/documents/{doc_id}").json()["data"]
    token = info["pages"][0]["token"]
    return client.get(f"/api/documents/{doc_id}/pages/0/render?scale=1&t={token}").content


# ------------------------------------------------------------------ the model
def test_no_comments_in_a_fresh_document(client, doc):
    assert listing(client, doc) == {"comments": [], "authors": [], "count": 0}


def test_note_comment_has_author_text_dates_and_a_unique_name(client, doc):
    xref = add(client, doc)
    note = by_xref(listing(client, doc), xref)
    assert (note["type"], note["author"], note["contents"], note["subject"]) == ("Text", "Alice", "Look here", "Sticky Note")
    assert note["page"] == 0 and note["parent"] is None and note["replies"] == []
    assert ISO.match(note["created"]) and ISO.match(note["modified"])
    assert re.fullmatch(r"[0-9a-f-]{36}", note["name"])
    assert note["status"] == "none" and note["checked"] is False
    assert note["rect"][:2] == [100, 200]


def test_text_markup_comments_keep_the_quoted_text(client, doc):
    spans = client.get(f"{base(doc)}/pages/0/model").json()["data"]["text"]["words"]
    word = next(w for w in spans if w["text"] == "Invoice")
    kinds = ["highlight", "underline", "strikeout", "squiggly"]
    xrefs = {kind: add(client, doc, kind=kind, rects=[word["bbox"]], text=f"{kind} remark") for kind in kinds}
    data = listing(client, doc)
    types = {kind: by_xref(data, xref) for kind, xref in xrefs.items()}
    assert [types[k]["type"] for k in kinds] == ["Highlight", "Underline", "StrikeOut", "Squiggly"]
    for kind, comment in types.items():
        assert comment["contents"] == f"{kind} remark"
        assert comment["quote"] == "Invoice"


def test_free_text_comment(client, doc):
    xref = add(client, doc, kind="textbox", rect=[50, 300, 250, 350], text="A text box", point=None)
    box = by_xref(listing(client, doc), xref)
    assert (box["type"], box["contents"], box["subject"]) == ("FreeText", "A text box", "Text Box")


def test_invalid_comments_are_refused(client, doc):
    assert client.post(f"{base(doc)}/comments", json={"page": 0, "kind": "bogus"}).status_code == 422
    assert client.post(f"{base(doc)}/comments", json={"page": 0, "kind": "note"}).status_code == 400
    assert client.post(f"{base(doc)}/comments", json={"page": 0, "kind": "highlight", "rects": []}).status_code == 400
    assert client.post(f"{base(doc)}/comments", json={"page": 9, "kind": "note", "point": [1, 1]}).status_code == 400
    too_long = {"page": 0, "kind": "note", "point": [1, 1], "text": "x" * 20001}
    assert client.post(f"{base(doc)}/comments", json=too_long).status_code == 422
    assert listing(client, doc)["count"] == 0


def test_comments_on_a_rotated_page_use_display_coordinates(client, doc):
    client.post(f"{base(doc)}/pages/rotate", json={"pages": [0], "angle": 90})
    xref = add(client, doc, point=[120, 60])
    assert by_xref(listing(client, doc), xref)["rect"][:2] == pytest.approx([120, 60], abs=0.01)


def test_edit_comment_text_and_subject(client, doc):
    xref = add(client, doc)
    response = client.patch(f"{base(doc)}/comments/0/{xref}", json={"text": "Changed\nover two lines", "subject": "Review"})
    assert response.status_code == 200
    note = by_xref(listing(client, doc), xref)
    assert note["contents"] == "Changed\nover two lines" and note["subject"] == "Review"
    assert note["author"] == "Alice"  # editing keeps who wrote it
    assert client.patch(f"{base(doc)}/comments/0/999999", json={"text": "x"}).status_code == 400


def test_editing_a_text_box_comment_redraws_it(client, doc):
    xref = add(client, doc, kind="textbox", rect=[50, 300, 250, 350], text="Before", point=None)
    before = render(client, doc["id"])
    client.patch(f"{base(doc)}/comments/0/{xref}", json={"text": "After the edit"})
    assert render(client, doc["id"]) != before


def test_comments_are_listed_in_page_order_and_authors_collected(client, doc):
    first = add(client, doc, page=1, point=[50, 50], author="Zed")
    second = add(client, doc, page=0, point=[300, 400], author="alice")
    third = add(client, doc, page=0, point=[100, 100], author="Bob")
    data = listing(client, doc)
    assert [c["xref"] for c in data["comments"]] == [third, second, first]
    assert data["authors"] == ["alice", "Bob", "Zed"]


# ------------------------------------------------------------------ replies
def test_reply_threads_nest_and_keep_their_order(client, doc):
    root = add(client, doc)
    first = reply(client, doc, root, "I agree", "Bob")
    nested = reply(client, doc, first, "Me too", "Carol")
    second = reply(client, doc, root, "A second thought", "Dan")
    thread = by_xref(listing(client, doc), root)["replies"]
    assert [(r["xref"], r["depth"], r["parent"]) for r in thread] == [
        (first, 1, root), (nested, 2, first), (second, 1, root)]
    assert [r["author"] for r in thread] == ["Bob", "Carol", "Dan"]
    assert [r["contents"] for r in thread] == ["I agree", "Me too", "A second thought"]
    assert listing(client, doc)["count"] == 4
    assert len(listing(client, doc)["comments"]) == 1  # replies are not comments of their own


def test_replies_are_not_objects_on_the_page_and_draw_nothing(client, doc):
    root = add(client, doc)
    before = render(client, doc["id"])
    reply(client, doc, root)
    assert render(client, doc["id"]) == before
    page = client.get(f"{base(doc)}/pages/0/model").json()["data"]
    assert [a["xref"] for a in page["annotations"]] == [root]


def test_reply_needs_text_and_an_existing_comment(client, doc):
    root = add(client, doc)
    assert client.post(f"{base(doc)}/comments/0/{root}/replies", json={"text": "", "author": "x"}).status_code == 422
    assert client.post(f"{base(doc)}/comments/0/{root}/replies", json={"text": "   ", "author": "x"}).status_code == 400
    assert client.post(f"{base(doc)}/comments/0/424242/replies", json={"text": "hello"}).status_code == 400


def test_replies_survive_saving_and_reopening(client, doc):
    root = add(client, doc)
    reply(client, doc, root, "I agree", "Bob")
    reopened = fitz.open(stream=current_pdf(client, doc["id"]).tobytes())
    thread = comments.list_comments(reopened)["comments"][0]
    assert thread["contents"] == "Look here" and [r["contents"] for r in thread["replies"]] == ["I agree"]


def test_adding_a_reply_can_be_undone(client, doc):
    root = add(client, doc)
    reply(client, doc, root)
    client.post(f"{base(doc)}/undo")
    assert by_xref(listing(client, doc), root)["replies"] == []


# ------------------------------------------------------------------ review status
def set_status(client, doc: dict, xref: int, **body) -> dict:
    return client.put(f"{base(doc)}/comments/0/{xref}/status", json=body)


def test_review_status_follows_the_latest_change(client, doc):
    root = add(client, doc)
    assert by_xref(listing(client, doc), root)["status"] == "none"
    for status in ["accepted", "rejected", "cancelled", "completed"]:
        assert set_status(client, doc, root, status=status, author="Carol").status_code == 200
        note = by_xref(listing(client, doc), root)
        assert (note["status"], note["statusBy"]) == (status, "Carol")
        assert ISO.match(note["statusDate"])
    set_status(client, doc, root, status="none", author="Dan")
    note = by_xref(listing(client, doc), root)
    assert (note["status"], note["statusBy"]) == ("none", "Dan")


def test_status_belongs_to_one_comment_or_reply(client, doc):
    root = add(client, doc)
    answer = reply(client, doc, root)
    set_status(client, doc, answer, status="rejected", author="Carol")
    data = listing(client, doc)
    assert by_xref(data, root)["status"] == "none"
    assert by_xref(data, root)["replies"][0]["status"] == "rejected"
    assert data["count"] == 2  # a status is not a comment and not a reply


def test_checkmark_is_separate_from_status(client, doc):
    root = add(client, doc)
    set_status(client, doc, root, checked=True, author="Bob")
    set_status(client, doc, root, status="accepted", author="Bob")
    note = by_xref(listing(client, doc), root)
    assert (note["checked"], note["status"]) == (True, "accepted")
    set_status(client, doc, root, checked=False, author="Bob")
    assert by_xref(listing(client, doc), root)["checked"] is False


def test_invalid_status_is_refused(client, doc):
    root = add(client, doc)
    assert set_status(client, doc, root, status="approved").status_code == 422
    assert set_status(client, doc, root, author="x").status_code == 422
    assert set_status(client, doc, 424242, status="accepted").status_code == 400


def test_status_is_recorded_the_way_acrobat_does(client, doc):
    root = add(client, doc)
    set_status(client, doc, root, status="accepted", author="Carol")
    pdf = current_pdf(client, doc["id"])
    page = pdf[0]
    states = [a.xref for a in page.annots() if a.irt_xref == root]
    assert len(states) == 1
    assert pdf.xref_get_key(states[0], "StateModel")[1] == "Review"
    assert pdf.xref_get_key(states[0], "State")[1] == "Accepted"
    assert pdf.xref_get_key(states[0], "RT")[1] == "/R"


# ------------------------------------------------------------------ deleting
def test_deleting_a_comment_deletes_its_replies_and_statuses(client, doc):
    keep = add(client, doc, point=[300, 300], author="Zed")
    root = add(client, doc)
    answer = reply(client, doc, root)
    reply(client, doc, answer, "deeper")
    set_status(client, doc, root, status="accepted", author="Carol")
    response = client.delete(f"{base(doc)}/comments/0/{root}")
    assert response.status_code == 200
    assert response.json()["data"]["result"]["removed"] == 4
    data = listing(client, doc)
    assert [c["xref"] for c in data["comments"]] == [keep] and data["count"] == 1
    pdf = current_pdf(client, doc["id"])
    page = pdf[0]
    assert [a.type[1] for a in page.annots()] == ["Text"]


def test_deleting_a_reply_keeps_the_rest_of_the_thread(client, doc):
    root = add(client, doc)
    first = reply(client, doc, root, "one")
    nested = reply(client, doc, first, "nested")
    second = reply(client, doc, root, "two")
    client.delete(f"{base(doc)}/comments/0/{first}")
    thread = by_xref(listing(client, doc), root)["replies"]
    assert [r["xref"] for r in thread] == [second]
    assert nested not in [r["xref"] for r in thread]


def test_deleting_a_missing_comment_fails_cleanly(client, doc):
    assert client.delete(f"{base(doc)}/comments/0/424242").status_code == 400


def test_deleting_the_annotation_on_the_page_takes_its_thread_along(client, doc):
    root = add(client, doc)
    reply(client, doc, root)
    assert client.delete(f"{base(doc)}/annotations/0/{root}").status_code == 200
    assert listing(client, doc)["count"] == 0
    pdf = current_pdf(client, doc["id"])
    page = pdf[0]
    assert list(page.annots() or []) == []


# ------------------------------------------------------------------ annotations made elsewhere
def test_annotations_made_by_the_editor_get_a_name_and_dates(client, doc):
    style = {"color": "#2563eb", "fill": None, "opacity": 1, "width": 2, "dashed": False, "contents": "", "author": "Eve"}
    response = client.post(f"{base(doc)}/annotations", json={"page": 0, "kind": "rect", "start": [50, 50], "end": [150, 120], "style": style})
    xref = response.json()["data"]["result"]
    shape = by_xref(listing(client, doc), xref)
    assert (shape["type"], shape["author"]) == ("Square", "Eve")
    assert re.fullmatch(r"[0-9a-f-]{36}", shape["name"]) and ISO.match(shape["created"])


def test_moving_a_drawing_keeps_its_replies_name_and_date(client, doc):
    style = {"color": "#e11d48", "fill": None, "opacity": 1, "width": 2, "dashed": False, "contents": "", "author": "Eve"}
    xref = client.post(f"{base(doc)}/annotations", json={"page": 0, "kind": "ink", "paths": [[[60, 300], [90, 330], [120, 300]]], "style": style}).json()["data"]["result"]
    answer = reply(client, doc, xref, "nice curve")
    before = by_xref(listing(client, doc), xref)
    moved = client.patch(f"{base(doc)}/annotations/0/{xref}", json={"style": style, "rect": [160, 300, 260, 340]})
    assert moved.status_code == 200
    after = listing(client, doc)["comments"][0]
    assert (after["name"], after["created"]) == (before["name"], before["created"])
    assert [r["contents"] for r in after["replies"]] == ["nice curve"]
    assert answer in [r["xref"] for r in after["replies"]]
    assert after["rect"][0] > before["rect"][0] + 50


# ------------------------------------------------------------------ damaged files
def test_reply_loops_and_dangling_replies_do_not_break_the_list(client, sample_pdf):
    src = fitz.open(stream=sample_pdf)
    page = src[0]
    a = page.add_text_annot((50, 50), "a")
    b = page.add_text_annot((90, 50), "b")
    c = page.add_text_annot((130, 50), "c")
    src.xref_set_key(a.xref, "IRT", f"{b.xref} 0 R")  # a answers b, b answers a: a loop
    src.xref_set_key(b.xref, "IRT", f"{a.xref} 0 R")
    src.xref_set_key(c.xref, "IRT", "99999 0 R")  # answers something that does not exist
    response = client.post("/api/documents", files={"file": ("loop.pdf", src.tobytes(), "application/pdf")})
    info = response.json()["data"]
    data = listing(client, info)
    assert data["count"] == 3
    top = {c["contents"]: c for c in data["comments"]}
    assert sorted(top) == ["b", "c"]  # the loop is broken once; the dangling reply stands on its own
    assert [r["contents"] for r in top["b"]["replies"]] == ["a"]


def test_endless_reply_chains_are_cut_off(client, sample_pdf):
    src = fitz.open(stream=sample_pdf)
    page = src[0]
    chain = [page.add_text_annot((50 + i, 50), f"r{i}") for i in range(comments.MAX_THREAD_DEPTH + 30)]
    for parent, child in zip(chain, chain[1:]):
        src.xref_set_key(child.xref, "IRT", f"{parent.xref} 0 R")
    info = client.post("/api/documents", files={"file": ("chain.pdf", src.tobytes(), "application/pdf")}).json()["data"]
    data = listing(client, info)
    assert data["count"] == len(chain)
    assert max(r["depth"] for c in data["comments"] for r in c["replies"]) <= comments.MAX_THREAD_DEPTH


# ------------------------------------------------------------------ dates
def test_pdf_dates_round_trip_with_time_zones():
    moment = parse_pdf_date("D:20240102030405+05'30'")
    assert moment is not None and moment.utcoffset().total_seconds() == 5.5 * 3600
    assert format_pdf_date(moment) == "D:20240102030405+05'30'"
    assert to_iso("D:20240102030405+05'30'") == "2024-01-01T21:34:05Z"
    assert to_iso("D:20240102030405Z") == "2024-01-02T03:04:05Z"
    assert to_iso("D:2024") == "2024-01-01T00:00:00Z"


@pytest.mark.parametrize("text", ["", None, "yesterday", "D:20241345", "D:2024010203040599+99'99'"])
def test_unreadable_dates_are_empty_not_errors(text):
    assert to_iso(text) == ""
