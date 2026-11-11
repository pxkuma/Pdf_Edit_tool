"""HTTP surface of digital signatures: /sign, /signatures, and how signed documents are stored and edited."""

from __future__ import annotations

import pytest
from sigkit import PASSWORD, make_credential

from conftest import current_pdf, page_spans


@pytest.fixture(scope="module")
def p12() -> bytes:
    return make_credential("API Signer").p12()


def sign(client, doc_id: str, p12: bytes, password: str = PASSWORD, **fields):
    data = {"password": password, **{k: str(v) for k, v in fields.items()}}
    files = {"certificate": ("me.p12", p12, "application/x-pkcs12")}
    return client.post(f"/api/documents/{doc_id}/sign", data=data, files=files)


def statuses(client, doc_id: str) -> dict:
    response = client.get(f"/api/documents/{doc_id}/signatures")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_unsigned_document_has_no_signatures(client, doc):
    assert doc["signatures"] == 0
    data = statuses(client, doc["id"])
    assert data["signatures"] == [] and data["summary"]["overall"] == "none"


def test_sign_visible_then_validate(client, doc, p12):
    response = sign(client, doc["id"], p12, page=0, rect="72,600,272,660", reason="Approved", location="Lab", utc_offset=120)
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["document"]["signatures"] == 1
    assert body["document"]["history"][-1]["label"] == "Digitally signed by API Signer"
    assert body["result"] == {"field": "Signature1", "signer": "API Signer", "visible": True, "timestamped": False}
    data = statuses(client, doc["id"])
    (report,) = data["signatures"]
    assert report["intact"] and report["valid"] and report["covers_whole_file"]
    assert report["status"] == "unknown" and report["signer"]["self_signed"]
    assert report["page"] == 0 and report["rect"] == pytest.approx([72, 600, 272, 660], abs=0.01)
    assert report["reason"] == "Approved" and report["location"] == "Lab"


def test_wrong_password_is_a_clear_error(client, doc, p12):
    response = sign(client, doc["id"], p12, password="hunter2-wrong")
    assert response.status_code == 400
    assert "password is incorrect" in response.json()["error"]
    assert "hunter2-wrong" not in response.text
    assert client.get(f"/api/documents/{doc['id']}").json()["data"]["signatures"] == 0


def test_invalid_requests_are_rejected(client, doc, p12):
    assert sign(client, doc["id"], p12, page=0).status_code == 400  # page without a box
    assert sign(client, doc["id"], p12, page=0, rect="1,2,3").status_code == 400
    assert sign(client, doc["id"], p12, page=9, rect="72,600,272,660").status_code == 400
    assert sign(client, doc["id"], b"not a certificate").status_code == 400
    ftp = sign(client, doc["id"], p12, timestamp_url="ftp://tsa.example.com")
    assert ftp.status_code == 400 and "http" in ftp.json()["error"]
    local = sign(client, doc["id"], p12, timestamp_url="http://127.0.0.1:9/tsa")
    assert local.status_code == 400 and "public address" in local.json()["error"]


def test_editing_after_signing_is_reported(client, doc, p12):
    assert sign(client, doc["id"], p12).status_code == 200
    edit = client.post(f"/api/documents/{doc['id']}/pages/rotate", json={"pages": [1], "angle": 90})
    assert edit.status_code == 200, edit.text
    (report,) = statuses(client, doc["id"])["signatures"]
    assert report["intact"], "edits to a signed document are appended, the signed revision stays intact"
    assert not report["covers_whole_file"]
    assert report["status"] == "modified" and not report["changes_allowed"]


def test_second_signature_keeps_the_first_valid(client, doc, p12):
    other = make_credential("Second API Signer").p12("other pass")
    assert sign(client, doc["id"], p12, page=0, rect="72,600,272,660").status_code == 200
    response = sign(client, doc["id"], other, password="other pass", page=1, rect="72,600,272,660")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["document"]["signatures"] == 2
    first, second = statuses(client, doc["id"])["signatures"]
    assert first["intact"] and first["changes_allowed"] and first["modification"] == "form_filling"
    assert second["intact"] and second["covers_whole_file"]
    assert second["field"] == "Signature2" and second["page"] == 1


def test_signed_upload_and_export_keep_the_exact_bytes(client, doc, p12):
    assert sign(client, doc["id"], p12).status_code == 200
    from app import deps

    signed = deps.store().current_bytes(doc["id"])
    uploaded = client.post("/api/documents", files={"file": ("signed.pdf", signed, "application/pdf")})
    assert uploaded.status_code == 200
    new_id = uploaded.json()["data"]["id"]
    assert deps.store().current_bytes(new_id) == signed, "rewriting on upload would break the signature"
    assert uploaded.json()["data"]["signatures"] == 1
    exported = client.post(f"/api/documents/{new_id}/export", json={})
    assert exported.status_code == 200 and exported.content == signed
    rewritten = client.post(f"/api/documents/{new_id}/export", json={"keep_signatures": False})
    assert rewritten.status_code == 200 and rewritten.content != signed


def test_certificate_is_never_written_to_storage(client, doc, data_dir):
    credential = make_credential("Storage Check")
    assert sign(client, doc["id"], credential.p12()).status_code == 200
    from cryptography.hazmat.primitives import serialization

    key_der = credential.key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    p12_bytes = credential.p12()
    for path in data_dir.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert key_der not in content and p12_bytes[:64] not in content, path
            assert PASSWORD.encode() not in content, path


def test_undo_returns_to_the_unsigned_version(client, doc, p12):
    assert sign(client, doc["id"], p12).status_code == 200
    undone = client.post(f"/api/documents/{doc['id']}/undo").json()["data"]
    assert undone["signatures"] == 0
    assert current_pdf(client, doc["id"]).get_sigflags() < 1


def test_text_edit_on_a_signed_document_invalidates_the_signature(client, doc, p12):
    """Text edits remove glyphs by redaction, which must not leave the old text in an earlier revision."""
    assert sign(client, doc["id"], p12, page=0, rect="300,700,500,760").status_code == 200
    span = next(s for s in page_spans(client, doc["id"]) if "Invoice" in s["text"])
    edit = client.post(f"/api/documents/{doc['id']}/text/span", json={
        "page": 0, "bbox": span["bbox"], "origin": span["origin"], "original_text": span["text"], "text": "Invoice number 99999"})
    assert edit.status_code == 200, edit.text
    assert "99999" in current_pdf(client, doc["id"])[0].get_text()
    (report,) = statuses(client, doc["id"])["signatures"]
    assert not report["intact"] and report["status"] == "invalid"
