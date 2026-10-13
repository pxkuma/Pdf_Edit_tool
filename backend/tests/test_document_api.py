"""Document lifecycle, history, pages, annotations, forms, tools and export."""

from __future__ import annotations

import io
import zipfile

import pymupdf as fitz

from conftest import current_pdf, page_spans


def _png(width=40, height=20, color=(255, 0, 0)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), 0)
    pix.set_rect(pix.irect, color)
    return pix.tobytes("png")


def test_upload_info_and_render(client, doc):
    assert len(doc["pages"]) == 2
    assert doc["canUndo"] is False
    token = doc["pages"][0]["token"]
    response = client.get(f"/api/documents/{doc['id']}/pages/0/render?scale=1&t={token}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert "immutable" in response.headers["cache-control"]
    stale = client.get(f"/api/documents/{doc['id']}/pages/0/render?scale=1&t=stale")
    assert stale.headers["cache-control"] == "no-store"


def test_invalid_upload_and_unknown_document(client):
    bad = client.post("/api/documents", files={"file": ("x.pdf", b"not a pdf at all", "application/pdf")})
    assert bad.status_code == 400
    assert client.get("/api/documents/" + "0" * 32).status_code == 404
    assert client.get("/api/documents/../../etc").status_code in (404, 400)


def test_password_protected_upload(client, sample_pdf):
    src = fitz.open(stream=sample_pdf)
    locked = src.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    response = client.post("/api/documents", files={"file": ("locked.pdf", locked, "application/pdf")})
    assert response.status_code == 401
    assert response.json()["code"] == "password_required"
    opened = client.post("/api/documents", files={"file": ("locked.pdf", locked, "application/pdf")}, data={"password": "secret"})
    assert opened.status_code == 200
    assert opened.json()["data"]["wasEncrypted"] is True


def test_image_upload_is_converted(client):
    response = client.post("/api/documents", files={"file": ("photo.png", _png(200, 100), "image/png")})
    assert response.status_code == 200
    assert len(response.json()["data"]["pages"]) == 1


def test_undo_redo_restores_tokens(client, doc):
    doc_id = doc["id"]
    original_tokens = [p["token"] for p in doc["pages"]]
    edited = client.post(f"/api/documents/{doc_id}/pages/rotate", json={"pages": [0], "angle": 90}).json()["data"]["document"]
    assert edited["pages"][0]["rotation"] == 90
    assert edited["pages"][0]["token"] != original_tokens[0]
    assert edited["pages"][1]["token"] == original_tokens[1]
    undone = client.post(f"/api/documents/{doc_id}/undo").json()["data"]
    assert [p["token"] for p in undone["pages"]] == original_tokens
    assert undone["canRedo"] is True
    redone = client.post(f"/api/documents/{doc_id}/redo").json()["data"]
    assert redone["pages"][0]["rotation"] == 90
    jumped = client.post(f"/api/documents/{doc_id}/history/0").json()["data"]
    assert jumped["pages"][0]["rotation"] == 0


def test_page_operations(client, doc):
    doc_id = doc["id"]
    base = f"/api/documents/{doc_id}/pages"
    info = client.post(f"{base}/duplicate", json={"pages": [0]}).json()["data"]["document"]
    assert len(info["pages"]) == 3
    assert len({p["token"] for p in info["pages"]}) == 3
    info = client.post(f"{base}/insert-blank", json={"at": 3, "size": "letter"}).json()["data"]["document"]
    assert info["pages"][3]["width"] == 612
    info = client.post(f"{base}/reorder", json={"order": [3, 2, 1, 0]}).json()["data"]["document"]
    assert info["pages"][0]["width"] == 612
    info = client.post(f"{base}/delete", json={"pages": [0]}).json()["data"]["document"]
    assert len(info["pages"]) == 3
    bad = client.post(f"{base}/delete", json={"pages": [0, 1, 2]})
    assert bad.status_code == 400
    info = client.post(f"{base}/crop", json={"pages": [0], "rect": [50, 50, 400, 500]}).json()["data"]["document"]
    assert info["pages"][0]["width"] == 350
    info = client.post(f"{base}/reset-crop", json={"pages": [0]}).json()["data"]["document"]
    assert info["pages"][0]["width"] > 350


def test_insert_file(client, doc, sample_pdf):
    response = client.post(f"/api/documents/{doc['id']}/pages/insert-file", data={"at": "1"},
                           files={"file": ("other.pdf", sample_pdf, "application/pdf")})
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]["document"]["pages"]) == 4
    image = client.post(f"/api/documents/{doc['id']}/pages/insert-file", data={"at": "0"},
                        files={"file": ("img.png", _png(), "image/png")})
    assert len(image.json()["data"]["document"]["pages"]) == 5


def test_annotations_lifecycle(client, doc):
    doc_id = doc["id"]
    span = next(s for s in page_spans(client, doc_id) if "Hello" in s["text"])
    kinds = [
        {"kind": "highlight", "rects": [span["bbox"]]},
        {"kind": "underline", "rects": [span["bbox"]]},
        {"kind": "ink", "paths": [[[100, 400], [150, 420], [200, 410]]]},
        {"kind": "rect", "start": [100, 500], "end": [200, 560], "style": {"color": "#ff0000", "fill": "#00ff00"}},
        {"kind": "ellipse", "start": [250, 500], "end": [300, 560]},
        {"kind": "arrow", "start": [100, 600], "end": [250, 650]},
        {"kind": "note", "point": [400, 400], "text": "Check this"},
        {"kind": "textbox", "rect": [300, 650, 500, 700], "text": "Comment box"},
    ]
    for body in kinds:
        response = client.post(f"/api/documents/{doc_id}/annotations", json={"page": 0, **body})
        assert response.status_code == 200, (body["kind"], response.text)
    model = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]
    items = model["annotations"]
    assert len(items) == len(kinds)
    ink = next(a for a in items if a["type"] == "Ink")
    moved = client.patch(f"/api/documents/{doc_id}/annotations/0/{ink['xref']}",
                         json={"style": {"color": "#0000ff", "opacity": 0.5, "width": 3}, "rect": [10, 10, 110, 40]})
    assert moved.status_code == 200, moved.text
    rect_annot = next(a for a in client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]["annotations"] if a["type"] == "Square")
    resized = client.patch(f"/api/documents/{doc_id}/annotations/0/{rect_annot['xref']}",
                           json={"style": {"color": "#000000"}, "rect": [100, 100, 300, 200]})
    assert resized.status_code == 200
    deleted = client.delete(f"/api/documents/{doc_id}/annotations/0/{rect_annot['xref']}")
    assert deleted.status_code == 200
    final = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]["annotations"]
    assert len(final) == len(kinds) - 1


def test_images(client, doc):
    doc_id = doc["id"]
    response = client.post(f"/api/documents/{doc_id}/images", data={"page": "0", "rect": "100,600,200,650"},
                           files={"file": ("a.png", _png(), "image/png")})
    assert response.status_code == 200, response.text
    images = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]["images"]
    assert len(images) == 1
    xref = images[0]["xref"]
    assert client.get(f"/api/documents/{doc_id}/images/{xref}").status_code == 200
    moved = client.post(f"/api/documents/{doc_id}/images/0/{xref}/move", json={"rect": [300, 300, 400, 350]})
    assert moved.status_code == 200, moved.text
    images = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]["images"]
    visible = [i for i in images if i["bbox"][0] >= 299]
    assert visible
    replaced = client.post(f"/api/documents/{doc_id}/images/0/{visible[0]['xref']}/replace",
                           files={"file": ("b.png", _png(color=(0, 0, 255)), "image/png")})
    assert replaced.status_code == 200, replaced.text
    assert client.delete(f"/api/documents/{doc_id}/images/0/{visible[0]['xref']}").status_code == 200


def test_redaction_removes_text(client, doc):
    span = next(s for s in page_spans(client, doc["id"]) if "Invoice" in s["text"])
    response = client.post(f"/api/documents/{doc['id']}/redact", json={"page": 0, "rects": [span["bbox"]], "mode": "redact"})
    assert response.status_code == 200
    assert "Invoice" not in current_pdf(client, doc["id"])[0].get_text()


def test_redact_search_and_whiteout(client, doc):
    response = client.post(f"/api/documents/{doc['id']}/redact/search", json={"query": "lazy dog"})
    assert response.json()["data"]["result"]["redacted"] == 1
    text = current_pdf(client, doc["id"])[0].get_text()
    assert "lazy dog" not in text
    span = next(s for s in page_spans(client, doc["id"]) if "Hello" in s["text"])
    response = client.post(f"/api/documents/{doc['id']}/redact", json={"page": 0, "rects": [span["bbox"]], "mode": "whiteout", "color": "#ffffff"})
    assert response.status_code == 200


def test_watermark_and_page_numbers(client, doc):
    response = client.post(f"/api/documents/{doc['id']}/watermark", json={"text": "CONFIDENTIAL", "layout": "tile"})
    assert response.status_code == 200, response.text
    response = client.post(f"/api/documents/{doc['id']}/header-footer", json={"template": "Page {n} of {total}"})
    assert response.status_code == 200, response.text
    pdf = current_pdf(client, doc["id"])
    assert "CONFIDENTIAL" in pdf[0].get_text()
    assert "Page 2 of 2" in pdf[1].get_text()
    image = client.post(f"/api/documents/{doc['id']}/watermark/image", data={"opacity": "0.2"},
                        files={"file": ("logo.png", _png(), "image/png")})
    assert image.status_code == 200, image.text


def test_search(client, doc):
    hits = client.get(f"/api/documents/{doc['id']}/search", params={"q": "page"}).json()["data"]
    assert any(hit["page"] == 1 for hit in hits)


def test_metadata_and_toc(client, doc):
    doc_id = doc["id"]
    assert client.get(f"/api/documents/{doc_id}/metadata").json()["data"]["title"] == "Sample"
    client.put(f"/api/documents/{doc_id}/metadata", json={"title": "New title", "author": "Me"})
    assert client.get(f"/api/documents/{doc_id}/metadata").json()["data"]["author"] == "Me"
    client.put(f"/api/documents/{doc_id}/toc", json={"items": [{"level": 1, "title": "Start", "page": 0},
                                                                 {"level": 2, "title": "Next", "page": 1}]})
    toc = client.get(f"/api/documents/{doc_id}/toc").json()["data"]
    assert [t["title"] for t in toc] == ["Start", "Next"]


def test_forms(client, doc):
    doc_id = doc["id"]
    assert client.post(f"/api/documents/{doc_id}/forms", json={"page": 0, "kind": "text", "rect": [100, 700, 300, 720], "name": "full_name"}).status_code == 200
    assert client.post(f"/api/documents/{doc_id}/forms", json={"page": 0, "kind": "checkbox", "rect": [320, 700, 335, 715], "name": "agree"}).status_code == 200
    fields = client.get(f"/api/documents/{doc_id}/forms").json()["data"]
    assert {f["name"] for f in fields} == {"full_name", "agree"}
    values = [{"page": f["page"], "xref": f["xref"], "value": "Jane Doe" if f["type"] == "text" else True} for f in fields]
    assert client.put(f"/api/documents/{doc_id}/forms", json={"values": values}).status_code == 200
    fields = client.get(f"/api/documents/{doc_id}/forms").json()["data"]
    assert next(f for f in fields if f["name"] == "full_name")["value"] == "Jane Doe"
    assert next(f for f in fields if f["name"] == "agree")["value"] is True
    assert client.post(f"/api/documents/{doc_id}/flatten", json={"annotations": True, "forms": True}).status_code == 200
    assert client.get(f"/api/documents/{doc_id}/forms").json()["data"] == []


def test_export_variants(client, doc):
    doc_id = doc["id"]
    plain = client.post(f"/api/documents/{doc_id}/export", json={})
    assert plain.status_code == 200 and plain.content.startswith(b"%PDF")
    assert fitz.open(stream=plain.content).page_count == 2
    locked = client.post(f"/api/documents/{doc_id}/export", json={"user_password": "pw", "allow_copy": False})
    locked_doc = fitz.open(stream=locked.content)
    assert locked_doc.needs_pass and locked_doc.authenticate("pw")
    images = client.post(f"/api/documents/{doc_id}/export/images", json={"dpi": 50})
    assert zipfile.ZipFile(io.BytesIO(images.content)).namelist() == ["page-0001.png", "page-0002.png"]
    extract = client.post(f"/api/documents/{doc_id}/export/extract", json={"pages": "2"})
    assert fitz.open(stream=extract.content).page_count == 1
    split = client.post(f"/api/documents/{doc_id}/export/split", json={"every": 1})
    assert len(zipfile.ZipFile(io.BytesIO(split.content)).namelist()) == 2
    text = client.get(f"/api/documents/{doc_id}/export/text")
    assert "Second page text" in text.text
    assert client.get(f"/api/documents/{doc_id}/original").content.startswith(b"%PDF")


def test_export_after_edit_keeps_text(client, doc):
    span = next(s for s in page_spans(client, doc["id"]) if "Invoice" in s["text"])
    client.post(f"/api/documents/{doc['id']}/text/span",
                json={"page": 0, "bbox": span["bbox"], "origin": span["origin"], "original_text": span["text"], "text": "Edited Ωmega"})
    exported = client.post(f"/api/documents/{doc['id']}/export", json={"subset_fonts": True})
    assert "Edited Ωmega" in fitz.open(stream=exported.content)[0].get_text()


def test_validation_errors(client, doc):
    response = client.post(f"/api/documents/{doc['id']}/pages/rotate", json={"pages": [0], "angle": 45})
    assert response.status_code == 422
    assert response.json()["ok"] is False
    response = client.post(f"/api/documents/{doc['id']}/pages/rotate", json={"pages": [99], "angle": 90})
    assert response.status_code == 400


def test_fonts_catalog(client):
    data = client.get("/api/fonts").json()["data"]
    assert data["families"]
    assert data["default"]
    assert client.get(f"/api/fonts/{data['default']}/file").status_code == 200


def test_revert(client, doc):
    client.post(f"/api/documents/{doc['id']}/pages/delete", json={"pages": [1]})
    reverted = client.post(f"/api/documents/{doc['id']}/revert").json()["data"]["document"]
    assert len(reverted["pages"]) == 2


def test_moving_an_annotation_keeps_its_size(client, doc):
    doc_id = doc["id"]
    body = {"page": 0, "kind": "rect", "start": [100, 500], "end": [200, 560], "style": {"color": "#ff0000", "width": 2}}
    assert client.post(f"/api/documents/{doc_id}/annotations", json=body).status_code == 200

    def square():
        model = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]
        return next(a for a in model["annotations"] if a["type"] == "Square")

    for step in range(3):
        annot = square()
        rect = [annot["rect"][0], annot["rect"][1] + 20, annot["rect"][2], annot["rect"][3] + 20]
        response = client.patch(f"/api/documents/{doc_id}/annotations/0/{annot['xref']}",
                                json={"style": {"color": "#ff0000", "width": 2}, "rect": rect})
        assert response.status_code == 200, response.text
        after = square()["rect"]
        assert all(abs(a - b) < 0.3 for a, b in zip(after, rect)), (step, rect, after)
