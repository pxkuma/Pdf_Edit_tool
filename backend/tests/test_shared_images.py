"""Moving or deleting an image on one page must not touch pages that reuse the same image object."""

from __future__ import annotations

import pymupdf as fitz
import pytest

from conftest import current_pdf

RED = (200, 50, 50)
WHITE = (255, 255, 255)
LOGO = fitz.Rect(50, 50, 150, 120)
LOGO_CENTER = (100, 85)
TARGET = [300, 300, 400, 370]
TARGET_CENTER = (350, 335)


def make_shared_image_pdf(share_resources: bool, pages: int = 3) -> bytes:
    """A logo placed on every page from ONE image object (like a header logo)."""
    doc = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.set_rect(pix.irect, RED)
    first = doc.new_page()
    xref = first.insert_image(LOGO, pixmap=pix)
    for _ in range(pages - 1):
        doc.new_page().insert_image(LOGO, xref=xref)
    if share_resources:
        # Word and LaTeX often point every page at one Resources dictionary.
        shared = doc.xref_get_key(doc.page_xref(0), "Resources")[1]
        for index in range(1, doc.page_count):
            doc.xref_set_key(doc.page_xref(index), "Resources", shared)
    return doc.tobytes(garbage=1, deflate=True)


def pixel(doc: fitz.Document, page: int, point: tuple[int, int]) -> tuple[int, int, int]:
    return tuple(doc[page].get_pixmap(dpi=72, alpha=False).pixel(*point))


def logo_xref(client, doc_id: str) -> int:
    model = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]
    return next(i["xref"] for i in model["images"] if i["editable"])


@pytest.fixture(params=[False, True], ids=["own-resources", "shared-resources"])
def logo_doc(client, request) -> dict:
    payload = make_shared_image_pdf(share_resources=request.param)
    response = client.post("/api/documents", files={"file": ("logo.pdf", payload, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_fixture_really_shares_the_image(client, logo_doc):
    pdf = current_pdf(client, logo_doc["id"])
    assert {pdf[i].get_images()[0][0] for i in range(3)} == {logo_xref(client, logo_doc["id"])}
    assert [pixel(pdf, i, LOGO_CENTER) for i in range(3)] == [RED, RED, RED]


def test_delete_image_only_affects_its_page(client, logo_doc):
    doc_id = logo_doc["id"]
    xref = logo_xref(client, doc_id)
    response = client.delete(f"/api/documents/{doc_id}/images/0/{xref}")
    assert response.status_code == 200, response.text
    pdf = current_pdf(client, doc_id)
    assert pixel(pdf, 0, LOGO_CENTER) == WHITE
    assert pixel(pdf, 1, LOGO_CENTER) == RED
    assert pixel(pdf, 2, LOGO_CENTER) == RED


def test_move_image_only_affects_its_page(client, logo_doc):
    doc_id = logo_doc["id"]
    xref = logo_xref(client, doc_id)
    response = client.post(f"/api/documents/{doc_id}/images/0/{xref}/move", json={"rect": TARGET})
    assert response.status_code == 200, response.text
    pdf = current_pdf(client, doc_id)
    assert pixel(pdf, 0, LOGO_CENTER) == WHITE
    assert pixel(pdf, 0, TARGET_CENTER) == RED
    for other in (1, 2):
        assert pixel(pdf, other, LOGO_CENTER) == RED
        assert pixel(pdf, other, TARGET_CENTER) == WHITE


def test_move_keeps_the_original_image_object(client, logo_doc):
    """Moving re-uses the image object instead of re-encoding it, so it stays shared and small."""
    doc_id = logo_doc["id"]
    xref = logo_xref(client, doc_id)
    client.post(f"/api/documents/{doc_id}/images/0/{xref}/move", json={"rect": TARGET})
    pdf = current_pdf(client, doc_id)
    assert xref in {item[0] for item in pdf[0].get_images()}
    assert xref in {item[0] for item in pdf[1].get_images()}


def test_deleted_image_leaves_no_ghost_placement(client, logo_doc):
    doc_id = logo_doc["id"]
    xref = logo_xref(client, doc_id)
    client.delete(f"/api/documents/{doc_id}/images/0/{xref}")
    model = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]
    assert model["images"] == []
    other = client.get(f"/api/documents/{doc_id}/pages/1/model").json()["data"]
    assert len(other["images"]) == 1 and other["images"][0]["uses"] == 2


def test_delete_and_move_work_for_an_unshared_image(client, doc):
    from test_document_api import _png

    doc_id = doc["id"]
    client.post(f"/api/documents/{doc_id}/images", data={"page": "0", "rect": "100,600,200,650"},
                files={"file": ("a.png", _png(), "image/png")})
    xref = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]["images"][0]["xref"]
    assert client.post(f"/api/documents/{doc_id}/images/0/{xref}/move", json={"rect": TARGET}).status_code == 200
    images = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]["images"]
    assert len(images) == 1 and images[0]["bbox"][0] > 290
    assert client.delete(f"/api/documents/{doc_id}/images/0/{images[0]['xref']}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]["images"] == []


def _roundtrip(doc: fitz.Document) -> fitz.Document:
    return fitz.open(stream=doc.tobytes(garbage=1, deflate=True))


def _resources_text(doc: fitz.Document, page: int) -> str:
    return doc.xref_object(int(doc.xref_get_key(doc.page_xref(page), "Resources")[1].split()[0]), compressed=True)


@pytest.mark.parametrize("layout", ["inline", "inherited"])
def test_page_local_removal_with_unusual_resource_layouts(layout):
    """Resources written inside the page object, or inherited from the page tree, are handled too."""
    from app.pdf import images

    doc = fitz.open(stream=make_shared_image_pdf(share_resources=False))
    text = _resources_text(doc, 0)
    if layout == "inline":
        for index in range(3):
            doc.xref_set_key(doc.page_xref(index), "Resources", _resources_text(doc, index))
    else:
        pages_root = int(doc.xref_get_key(doc.pdf_catalog(), "Pages")[1].split()[0])
        doc.xref_set_key(pages_root, "Resources", text)
        for index in range(3):
            doc.xref_set_key(doc.page_xref(index), "Resources", "null")
    doc = _roundtrip(doc)
    assert [pixel(doc, i, LOGO_CENTER) for i in range(3)] == [RED, RED, RED]

    xref = doc[0].get_images()[0][0]
    images.delete_image(doc[0], xref)
    doc = _roundtrip(doc)
    assert [pixel(doc, i, LOGO_CENTER) for i in range(3)] == [WHITE, RED, RED]

    images.move_image(doc, doc[1], xref, tuple(TARGET))
    doc = _roundtrip(doc)
    assert [pixel(doc, i, LOGO_CENTER) for i in range(3)] == [WHITE, WHITE, RED]
    assert pixel(doc, 1, TARGET_CENTER) == RED
    assert pixel(doc, 2, TARGET_CENTER) == WHITE


def test_deleting_the_only_use_of_an_image_removes_its_data(client):
    from app.pdf import images

    doc = fitz.open(stream=make_shared_image_pdf(share_resources=False, pages=1))
    xref = doc[0].get_images()[0][0]
    images.delete_image(doc[0], xref)
    saved = _roundtrip(doc)
    assert saved[0].get_images() == []
    assert not any(saved.xref_is_image(x) for x in range(1, saved.xref_length()))


def test_image_inside_a_shared_form_is_removed_from_its_page_only(client):
    """An image that lives in a Form XObject (not in the page's own resources) is still page-local."""
    source = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.set_rect(pix.irect, RED)
    source.new_page(width=200, height=200).insert_image(fitz.Rect(10, 10, 110, 80), pixmap=pix)
    doc = fitz.open()
    for _ in range(2):
        doc.new_page().show_pdf_page(fitz.Rect(40, 40, 240, 240), source, 0)
    payload = doc.tobytes(garbage=1, deflate=True)
    created = client.post("/api/documents", files={"file": ("form.pdf", payload, "application/pdf")}).json()["data"]
    doc_id = created["id"]
    model = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]
    image = next(i for i in model["images"] if i["editable"])
    center = (int((image["bbox"][0] + image["bbox"][2]) / 2), int((image["bbox"][1] + image["bbox"][3]) / 2))
    assert pixel(current_pdf(client, doc_id), 1, center) == RED
    assert client.delete(f"/api/documents/{doc_id}/images/0/{image['xref']}").status_code == 200
    pdf = current_pdf(client, doc_id)
    assert pixel(pdf, 0, center) == WHITE
    assert pixel(pdf, 1, center) == RED
