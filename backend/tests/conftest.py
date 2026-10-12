from __future__ import annotations

import os
import sys
from pathlib import Path

import pymupdf as fitz
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FONT_DIRS = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]


def find_font(*names: str) -> str:
    for directory in FONT_DIRS:
        for name in names:
            matches = list(directory.rglob(name)) if directory.exists() else []
            if matches:
                return str(matches[0])
    pytest.skip(f"font {names} not installed")


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("pdfstudio")
    os.environ["PDF_STUDIO_DATA"] = str(path)
    os.environ["PDF_STUDIO_STATIC"] = str(path / "static")
    return path


@pytest.fixture(scope="session")
def client(data_dir):
    from fastapi.testclient import TestClient

    from app import deps

    deps.settings.cache_clear()
    deps.store.cache_clear()
    deps.catalog.cache_clear()
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def make_sample_pdf() -> bytes:
    """Two pages with subsetted embedded fonts, like real-world generated PDFs."""
    sans = find_font("LiberationSans-Regular.ttf")
    sans_bold = find_font("LiberationSans-Bold.ttf")
    serif = find_font("LiberationSerif-Regular.ttf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="F1", fontfile=sans)
    page.insert_font(fontname="F2", fontfile=sans_bold)
    page.insert_font(fontname="F3", fontfile=serif)
    page.insert_text((72, 100), "Invoice number 12345", fontname="F2", fontsize=16)
    page.insert_text((72, 130), "Hello world from the sample", fontname="F1", fontsize=12)
    after = 72 + fitz.Font(fontfile=sans).text_length("Hello world from the sample ", 12)
    page.insert_text((after, 130), "trailing words", fontname="F1", fontsize=12, color=(0.8, 0, 0))
    lines = ["The quick brown fox jumps over", "the lazy dog in a paragraph", "that spans three lines."]
    for index, line in enumerate(lines):
        page.insert_text((72, 180 + index * 15), line, fontname="F3", fontsize=12)
    page2 = doc.new_page()
    page2.insert_font(fontname="F1", fontfile=sans)
    page2.insert_text((72, 100), "Second page text", fontname="F1", fontsize=14)
    doc.set_metadata({"title": "Sample", "author": "Tester"})
    doc.subset_fonts()
    return doc.tobytes(garbage=3, deflate=True)


@pytest.fixture()
def sample_pdf() -> bytes:
    return make_sample_pdf()


@pytest.fixture()
def doc(client, sample_pdf) -> dict:
    response = client.post("/api/documents", files={"file": ("sample.pdf", sample_pdf, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def current_pdf(client, doc_id: str) -> fitz.Document:
    from app import deps

    return fitz.open(stream=deps.store().current_bytes(doc_id))


def page_spans(client, doc_id: str, page: int = 0) -> list[dict]:
    model = client.get(f"/api/documents/{doc_id}/pages/{page}/model").json()["data"]
    return [s for b in model["text"]["blocks"] for line in b["lines"] for s in line["spans"]]
