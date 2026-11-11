"""Large pages and documents must not exhaust memory or redo document-wide work for every request."""

from __future__ import annotations

import io
import zipfile

import pymupdf as fitz

from app.api import pages as pages_api
from app.pdf import doctools, images


def blank_pdf(pages: int = 1, width: float = 595, height: float = 842) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=width, height=height)
    return doc.tobytes()


def open_doc(client, payload: bytes, name: str = "t.pdf") -> dict:
    response = client.post("/api/documents", files={"file": (name, payload, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ------------------------------------------------------------------ D5: pixel caps
def test_normal_pages_keep_their_requested_zoom():
    a4 = fitz.Rect(0, 0, 595, 842)
    assert pages_api.render_bucket(a4, 8) == 8  # 8x A4 is about 32 megapixels
    assert pages_api.render_bucket(a4, 3) == 3


def test_huge_pages_are_rendered_at_a_lower_zoom():
    banner = fitz.Rect(0, 0, 14400, 14400)  # the largest page a PDF viewer has to handle
    bucket = pages_api.render_bucket(banner, 64)
    pixels = (banner.width * bucket / 8) * (banner.height * bucket / 8)
    assert 1 <= bucket < 64 and pixels <= pages_api.MAX_RENDER_PIXELS or bucket == 1


def test_render_endpoint_shrinks_an_oversized_request(client):
    doc = open_doc(client, blank_pdf(width=4000, height=4000))
    response = client.get(f"/api/documents/{doc['id']}/pages/0/render", params={"scale": 8})
    assert response.status_code == 200
    pix = fitz.Pixmap(response.content)
    assert pix.width * pix.height <= pages_api.MAX_RENDER_PIXELS


def test_export_dpi_is_lowered_for_huge_pages():
    a0 = fitz.Rect(0, 0, 2384, 3370)
    assert doctools.capped_dpi(fitz.Rect(0, 0, 595, 842), 300) == 300
    capped = doctools.capped_dpi(a0, 600)
    assert 36 <= capped < 600
    assert a0.width * capped / 72 * a0.height * capped / 72 <= doctools.MAX_EXPORT_PIXELS


def test_export_images_streams_every_page(client):
    doc = open_doc(client, blank_pdf(pages=3, width=200, height=200))
    response = client.post(f"/api/documents/{doc['id']}/export/images", json={"dpi": 50, "format": "jpg"})
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.namelist() == ["page-0001.jpg", "page-0002.jpg", "page-0003.jpg"]
    assert all(abs(fitz.Pixmap(archive.read(name)).width - 50 * 200 / 72) <= 1 for name in archive.namelist())


def test_page_images_are_produced_one_at_a_time():
    doc = fitz.open(stream=blank_pdf(pages=2, width=100, height=100))
    produced = doctools.iter_page_images(doc, [0, 1], 72, "png")
    assert next(produced)[0] == "page-0001.png"  # nothing beyond the first page was rendered yet
    assert [name for name, _data in produced] == ["page-0002.png"]


# ------------------------------------------------------------------ D6: image usage counts
def shared_logo_pdf(pages: int = 4) -> bytes:
    doc = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), 0)
    pix.set_rect(pix.irect, (10, 20, 30))
    first = doc.new_page()
    xref = first.insert_image(fitz.Rect(10, 10, 60, 60), pixmap=pix)
    for _ in range(pages - 1):
        doc.new_page().insert_image(fitz.Rect(10, 10, 60, 60), xref=xref)
    return doc.tobytes()


def test_usage_counts_cover_the_whole_document_in_one_pass():
    doc = fitz.open(stream=shared_logo_pdf(4))
    counts = images.usage_counts(doc)
    assert list(counts.values()) == [4]


def test_listing_images_scans_the_document_once_not_once_per_image(monkeypatch):
    doc = fitz.open(stream=shared_logo_pdf(4))
    page = doc[0]
    for _ in range(3):  # three more placements of the logo on the first page
        page.insert_image(fitz.Rect(100, 100, 150, 150), xref=page.get_images()[0][0])
    scans = []
    original = images.usage_counts

    def counting(document):
        scans.append(1)
        return original(document)

    monkeypatch.setattr(images, "usage_counts", counting)
    listed = images.list_images(doc, doc[0])
    assert len(listed) == 4 and {item["uses"] for item in listed} == {7}
    assert len(scans) == 1


def test_usage_counts_are_cached_per_version(client, monkeypatch):
    doc = open_doc(client, shared_logo_pdf(3))
    scans = []
    original = images.usage_counts
    monkeypatch.setattr(images, "usage_counts", lambda d: scans.append(1) or original(d))
    for index in range(3):
        model = client.get(f"/api/documents/{doc['id']}/pages/{index}/model").json()["data"]
        assert model["images"][0]["uses"] == 3
    assert len(scans) == 1
