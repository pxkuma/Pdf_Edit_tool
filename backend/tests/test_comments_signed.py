"""Comments on a digitally signed document: every comment change is appended after the signed revision."""

from __future__ import annotations

import pytest
from sigkit import make_credential
from test_comments import add, base, by_xref, listing, reply, set_status
from test_signature_api import sign, statuses
from test_xfdf import export, import_xfdf, report

from conftest import current_pdf


@pytest.fixture(scope="module")
def p12() -> bytes:
    return make_credential("Comment Signer").p12()


@pytest.fixture()
def signed(client, doc, p12) -> dict:
    assert sign(client, doc["id"], p12, page=0, rect="300,700,500,760").status_code == 200
    return doc


def only_signature(client, doc: dict) -> dict:
    (entry,) = statuses(client, doc["id"])["signatures"]
    return entry


def assert_signature_survives(client, doc: dict) -> None:
    entry = only_signature(client, doc)
    assert entry["intact"] and entry["valid"], "the signed revision must stay byte-for-byte intact"
    assert not entry["covers_whole_file"], "the comment change is appended after the signed revision"
    assert entry["status"] != "invalid"
    assert current_pdf(client, doc["id"]).get_sigflags() >= 1


def test_adding_a_comment_appends_a_revision_and_keeps_the_signature(client, signed):
    xref = add(client, signed, text="Please check the total")
    assert by_xref(listing(client, signed), xref)["contents"] == "Please check the total"
    assert_signature_survives(client, signed)


def test_editing_replying_and_reviewing_keep_the_signature(client, signed):
    root = add(client, signed, text="First", author="Alice")
    edited = client.patch(f"{base(signed)}/comments/0/{root}", json={"text": "Edited"})
    assert edited.status_code == 200, edited.text
    answer = reply(client, signed, root, "Agreed", "Bob")
    assert set_status(client, signed, root, status="accepted", author="Carol").status_code == 200
    assert set_status(client, signed, root, checked=True, author="Carol").status_code == 200
    comment = by_xref(listing(client, signed), root)
    assert comment["contents"] == "Edited" and comment["status"] == "accepted" and comment["checked"] is True
    assert [r["xref"] for r in comment["replies"]] == [answer]
    assert_signature_survives(client, signed)


def test_deleting_a_comment_and_its_thread_keeps_the_signature(client, signed):
    root = add(client, signed)
    reply(client, signed, root)
    removed = client.delete(f"{base(signed)}/comments/0/{root}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"]["result"]["removed"] == 2
    assert listing(client, signed)["count"] == 0
    assert_signature_survives(client, signed)


def test_importing_xfdf_keeps_the_signature(client, signed, sample_pdf):
    other = client.post("/api/documents", files={"file": ("other.pdf", sample_pdf, "application/pdf")}).json()["data"]
    root = add(client, other, text="From a reviewer", author="Dan")
    reply(client, other, root, "A reply", "Eve")
    result = report(import_xfdf(client, signed, export(client, other)))
    assert result["added"] == 2
    assert listing(client, signed)["count"] == 2
    assert_signature_survives(client, signed)


def test_undo_of_a_comment_on_a_signed_document_returns_to_the_signed_file(client, signed):
    from app import deps

    signed_bytes = deps.store().current_bytes(signed["id"])
    add(client, signed)
    undone = client.post(f"{base(signed)}/undo").json()["data"]
    assert undone["signatures"] == 1
    assert deps.store().current_bytes(signed["id"]) == signed_bytes
    entry = only_signature(client, signed)
    assert entry["intact"] and entry["covers_whole_file"]
