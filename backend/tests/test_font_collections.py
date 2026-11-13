"""Font collections (.ttc/.otc) in the catalog (audit C6)."""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest
from conftest import find_font
from fontTools.ttLib import TTCollection, TTFont

from app.pdf.fonts import FontCatalog
from app.pdf.textwriter import FontChain, PlacedLine, TextStyle, write_lines


@pytest.fixture()
def collection_dir(tmp_path) -> Path:
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    collection = TTCollection()
    collection.fonts = [TTFont(find_font("LiberationSans-Regular.ttf")), TTFont(find_font("LiberationSerif-Bold.ttf"))]
    collection.save(str(fonts / "Pair.ttc"))
    return fonts


def test_every_face_of_a_collection_is_cataloged(collection_dir, tmp_path):
    catalog = FontCatalog([collection_dir], tmp_path / "cache.json")
    faces = {(f.family, f.style, f.index) for f in catalog.faces()}
    assert ("Liberation Sans", "Regular", 0) in faces
    assert ("Liberation Serif", "Bold", 1) in faces


def test_collection_face_writes_and_reads_back(collection_dir, tmp_path):
    catalog = FontCatalog([collection_dir], tmp_path / "cache.json")
    face = next(f for f in catalog.faces() if f.index == 1)
    single = catalog.face_file(face)
    assert single.endswith(".ttf") and TTFont(single)["name"].getDebugName(1) == "Liberation Serif"
    doc = fitz.open()
    page = doc.new_page()
    chain = FontChain.build(catalog, None, face, include_coverage=False)
    glyphs = chain.encode("Collected")
    write_lines(doc, page, [PlacedLine((72, 100), (1.0, 0.0), glyphs)], TextStyle(size=12), chain)
    reopened = fitz.open("pdf", doc.tobytes())
    assert reopened[0].get_text().strip() == "Collected"
    assert not chain.missing


def test_system_cjk_collection_covers_chinese(tmp_path):
    cjk = list(Path("/usr/share/fonts").rglob("NotoSansCJK-Regular.ttc"))
    if not cjk:
        pytest.skip("Noto Sans CJK collection not installed")
    catalog = FontCatalog([cjk[0].parent], tmp_path / "cache.json")
    chain = FontChain.build(catalog, None, None)
    chain.encode("中文")
    assert not chain.missing
