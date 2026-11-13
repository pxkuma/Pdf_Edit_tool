"""HTTP surface of form authoring: create, edit, fill, reorder and recognise fields, and sign into a prepared field."""

from __future__ import annotations

import pymupdf as fitz
import pytest
from sigkit import PASSWORD, make_credential

from conftest import current_pdf


def url(doc_id: str, tail: str = "") -> str:
    return f"/api/documents/{doc_id}/forms{tail}"


def fields(client, doc_id: str) -> list[dict]:
    response = client.get(url(doc_id))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def add(client, doc_id: str, kind: str, rect, **props):
    name = props.pop("name", "")
    body = {"page": 0, "kind": kind, "rect": rect, "name": name, "props": props or None}
    response = client.post(url(doc_id), json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def fill(client, doc_id: str, field: dict, value):
    return client.put(url(doc_id), json={"values": [{"page": field["page"], "xref": field["xref"], "value": value}]})


def named(client, doc_id: str, name: str) -> list[dict]:
    return [f for f in fields(client, doc_id) if f["name"] == name]


# ------------------------------------------------------------------ create / edit / fill round trip
def test_every_field_type_can_be_created_over_http(client, doc):
    doc_id = doc["id"]
    add(client, doc_id, "text", [72, 700, 272, 720], name="t")
    add(client, doc_id, "checkbox", [72, 660, 86, 674], name="c")
    add(client, doc_id, "radio", [72, 620, 86, 634], name="r", export_value="A")
    add(client, doc_id, "radio", [100, 620, 114, 634], name="r", export_value="B")
    add(client, doc_id, "combobox", [72, 580, 272, 600], name="d", options=[{"value": "x", "label": "Ex"}])
    add(client, doc_id, "listbox", [72, 500, 272, 560], name="l", options=[{"value": "y"}, {"value": "z"}])
    add(client, doc_id, "button", [72, 460, 172, 484], name="b", caption="Reset", action="reset")
    result = add(client, doc_id, "signature", [72, 380, 272, 430], name="sig")
    assert result["document"]["hasForms"]
    kinds = sorted((f["name"], f["type"]) for f in fields(client, doc_id))
    assert kinds == [("b", "button"), ("c", "checkbox"), ("d", "combobox"), ("l", "listbox"),
                     ("r", "radio"), ("r", "radio"), ("sig", "signature"), ("t", "text")]
    # The saved file is a real AcroForm that PyMuPDF reads back from the stored bytes.
    stored = current_pdf(client, doc_id)
    assert {w.field_name for w in stored[0].widgets()} == {"t", "c", "r", "d", "l", "b", "sig"}


def test_create_edit_fill_reload_round_trip(client, doc):
    doc_id = doc["id"]
    add(client, doc_id, "text", [72, 700, 272, 720], name="amount")
    (field,) = named(client, doc_id, "amount")
    patch = client.patch(url(doc_id, f"/{field['page']}/{field['xref']}"), json={
        "tooltip": "Total due", "required": True, "align": "right", "font_size": 12,
        "format": {"kind": "number", "decimals": 2}, "rect": [80, 690, 300, 716]})
    assert patch.status_code == 200, patch.text
    assert fill(client, doc_id, field, "1,234.5").status_code == 200
    (field,) = named(client, doc_id, "amount")
    assert field["value"] == "1234.50" and field["tooltip"] == "Total due" and field["required"]
    assert field["align"] == "right" and field["format"]["kind"] == "number"
    assert field["rect"] == pytest.approx([80, 690, 300, 716], abs=0.01)
    # Survives an export-style reopen of the current bytes.
    reopened = [w for w in current_pdf(client, doc_id)[0].widgets() if w.field_name == "amount"]
    assert reopened and reopened[0].field_value == "1234.50"
    # Undo steps back through fill, edit and creation.
    assert client.post(f"/api/documents/{doc_id}/undo").status_code == 200


def test_invalid_input_is_a_clear_user_error(client, doc):
    doc_id = doc["id"]
    base = {"page": 0, "kind": "text", "rect": [72, 700, 272, 720]}
    too_small = client.post(url(doc_id), json={**base, "rect": [72, 700, 74, 702]})
    assert too_small.status_code == 400 and "too small" in too_small.json()["error"].lower()
    assert client.post(url(doc_id), json={**base, "kind": "hologram"}).status_code == 422
    unsafe = client.post(url(doc_id), json={**base, "kind": "button", "props": {"action": "url", "url": "javascript:alert(1)"}})
    assert unsafe.status_code == 422
    missing_url = client.post(url(doc_id), json={**base, "kind": "button", "props": {"action": "url"}})
    assert missing_url.status_code == 400
    assert client.post(url(doc_id), json={**base, "page": 9}).status_code == 400
    assert fields(client, doc_id) == []  # nothing half-created


def test_duplicate_names_are_rejected(client, doc):
    doc_id = doc["id"]
    add(client, doc_id, "text", [72, 700, 272, 720], name="email")
    again = client.post(url(doc_id), json={"page": 0, "kind": "text", "rect": [72, 660, 272, 680], "name": "email"})
    assert again.status_code == 400 and "already exists" in again.json()["error"]


def test_delete_field(client, doc):
    doc_id = doc["id"]
    add(client, doc_id, "text", [72, 700, 272, 720], name="gone")
    (field,) = fields(client, doc_id)
    assert client.delete(url(doc_id, f"/{field['page']}/{field['xref']}")).status_code == 200
    assert fields(client, doc_id) == []
    assert client.delete(url(doc_id, f"/0/{field['xref']}")).status_code == 400  # already gone


def test_batch_create_uniquifies_names(client, doc):
    doc_id = doc["id"]
    add(client, doc_id, "text", [72, 700, 272, 720], name="Name")
    body = {"fields": [
        {"page": 0, "kind": "text", "rect": [72, 650, 272, 670], "props": {"name": "Name"}},
        {"page": 1, "kind": "checkbox", "rect": [72, 650, 86, 664], "props": {"name": "Name"}},
    ]}
    response = client.post(url(doc_id, "/batch"), json=body)
    assert response.status_code == 200, response.text
    created = response.json()["data"]["result"]
    assert [c["name"] for c in created] == ["Name_2", "Name_3"]
    assert {f["page"] for f in fields(client, doc_id)} == {0, 1}


def test_list_box_and_radio_group_fill_over_http(client, doc):
    doc_id = doc["id"]
    add(client, doc_id, "radio", [72, 700, 86, 714], name="size", export_value="S")
    add(client, doc_id, "radio", [100, 700, 114, 714], name="size", export_value="M")
    add(client, doc_id, "listbox", [72, 600, 272, 660], name="langs", multi_select=True,
        options=[{"value": "en"}, {"value": "de"}, {"value": "fr"}])
    second = named(client, doc_id, "size")[1]
    assert fill(client, doc_id, second, True).status_code == 200
    assert [f["value"] for f in named(client, doc_id, "size")] == [False, True]
    (langs,) = named(client, doc_id, "langs")
    assert fill(client, doc_id, langs, ["en", "fr"]).status_code == 200
    assert named(client, doc_id, "langs")[0]["value"] == ["en", "fr"]
    bad = fill(client, doc_id, langs, ["nope"])
    assert bad.status_code == 400 and "not one of the options" in bad.json()["error"]


def test_page_model_carries_authoring_properties(client, doc):
    doc_id = doc["id"]
    add(client, doc_id, "combobox", [72, 700, 272, 720], name="d", options=[{"value": "a", "label": "Alpha"}])
    model = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]
    (field,) = model["fields"]
    assert field["choices"] == [{"value": "a", "label": "Alpha"}] and field["tabIndex"] == 0


# ------------------------------------------------------------------ tab order
def test_tab_order_row_column_and_manual(client, doc):
    doc_id = doc["id"]
    # Display space: y grows downwards, so the "top" row has the smaller y.
    add(client, doc_id, "text", [300, 100, 400, 120], name="top_right")
    add(client, doc_id, "text", [72, 100, 172, 120], name="top_left")
    add(client, doc_id, "text", [72, 200, 172, 220], name="bottom_left")
    state = client.get(url(doc_id, "/tab-order/0")).json()["data"]
    assert state["mode"] == "manual" and [f["name"] for f in state["fields"]] == ["top_right", "top_left", "bottom_left"]

    def order(mode, ids=None):
        body = {"page": 0, "mode": mode, "order": ids}
        response = client.put(url(doc_id, "/tab-order"), json=body)
        assert response.status_code == 200, response.text
        listed = client.get(url(doc_id, "/tab-order/0")).json()["data"]
        return listed["mode"], [f["name"] for f in listed["fields"]]

    assert order("row") == ("row", ["top_left", "top_right", "bottom_left"])
    assert order("column") == ("column", ["top_left", "bottom_left", "top_right"])
    ids = [f["xref"] for f in client.get(url(doc_id, "/tab-order/0")).json()["data"]["fields"]]
    assert order("manual", list(reversed(ids)))[1] == ["top_right", "bottom_left", "top_left"]
    assert [f["name"] for f in fields(client, doc_id)] == ["top_right", "bottom_left", "top_left"]  # /Annots order
    wrong = client.put(url(doc_id, "/tab-order"), json={"page": 0, "mode": "manual", "order": ids[:2]})
    assert wrong.status_code == 400


# ------------------------------------------------------------------ recognition
def make_form_like_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Full name:", fontsize=11)
    page.draw_line((150, 102), (400, 102), width=0.7)
    page.insert_text((72, 150), "Signature:", fontsize=11)
    page.draw_line((150, 152), (400, 152), width=0.7)
    page.draw_rect(fitz.Rect(72, 190, 84, 202), width=0.8)
    page.insert_text((92, 200), "I agree to the terms", fontsize=11)
    page.insert_text((72, 300), "Plain paragraph text that is not a form at all.", fontsize=11)
    return doc.tobytes()


def test_detect_proposes_fields_without_changing_the_document(client):
    created = client.post("/api/documents", files={"file": ("f.pdf", make_form_like_pdf(), "application/pdf")})
    doc = created.json()["data"]
    response = client.post(url(doc["id"], "/detect"), json={"pages": [0]})
    assert response.status_code == 200, response.text
    proposals = response.json()["data"]
    kinds = {p["label"]: p["kind"] for p in proposals}
    assert kinds.get("Full name") == "text"
    assert kinds.get("Signature") == "signature"
    assert kinds.get("I agree to the terms") == "checkbox"
    assert all(0 < p["confidence"] <= 1 and len(p["rect"]) == 4 for p in proposals)
    assert fields(client, doc["id"]) == []  # read-only
    assert client.get(f"/api/documents/{doc['id']}").json()["data"]["history"] == doc["history"]
    # Accepting proposals goes through the batch endpoint.
    accept = [{"page": p["page"], "kind": p["kind"], "rect": p["rect"], "props": {"name": p["name"]}} for p in proposals]
    assert client.post(url(doc["id"], "/batch"), json={"fields": accept}).status_code == 200
    assert len(fields(client, doc["id"])) == len(proposals)
    # Fields that now exist are not proposed again.
    again = client.post(url(doc["id"], "/detect"), json={"pages": [0]}).json()["data"]
    assert again == []


def test_detect_validates_pages(client, doc):
    assert client.post(url(doc["id"], "/detect"), json={"pages": [7]}).status_code == 400
    assert client.post(url(doc["id"], "/detect"), json={"pages": []}).status_code == 422


# ------------------------------------------------------------------ signing into a prepared signature field
@pytest.fixture(scope="module")
def p12() -> bytes:
    return make_credential("Form Signer").p12()


def sign_into(client, doc_id: str, p12: bytes, field: str):
    files = {"certificate": ("me.p12", p12, "application/x-pkcs12")}
    return client.post(f"/api/documents/{doc_id}/sign", data={"password": PASSWORD, "field": field}, files=files)


def test_sign_into_a_prepared_signature_field(client, doc, p12):
    doc_id = doc["id"]
    add(client, doc_id, "signature", [72, 600, 272, 660], name="Approver")
    response = sign_into(client, doc_id, p12, "Approver")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["result"]["field"] == "Approver"
    (report,) = client.get(f"/api/documents/{doc_id}/signatures").json()["data"]["signatures"]
    assert report["field"] == "Approver" and report["valid"] and report["rect"] == pytest.approx([72, 600, 272, 660], abs=0.01)
    (signature,) = [f for f in fields(client, doc_id) if f["type"] == "signature"]
    assert signature["signed"]
    # A signed field cannot be edited or deleted, and cannot be signed twice.
    assert client.delete(url(doc_id, f"/0/{signature['xref']}")).status_code == 400
    assert client.patch(url(doc_id, f"/0/{signature['xref']}"), json={"tooltip": "x"}).status_code == 400
    assert sign_into(client, doc_id, p12, "Approver").status_code == 400


def test_signing_into_a_missing_field_is_a_clear_error(client, doc, p12):
    response = sign_into(client, doc["id"], p12, "Nope")
    assert response.status_code == 400 and "no signature field" in response.json()["error"]
