"""Small PDFs for the document comparison tests."""

from __future__ import annotations

import pymupdf as fitz

LINE_STEP = 24
FIRST_LINE_Y = 100


def paragraph(topic: str, lines: int = 3) -> list[str]:
    """Distinct, realistic-looking lines so two pages of different topics do not resemble each other."""
    return [f"{topic} line {n} carries unique {topic} wording number {n * 7}" for n in range(1, lines + 1)]


def make_pdf(pages: list[list[str]], *, size: tuple[float, float] = (595, 842), boxes: dict[int, list[tuple]] | None = None) -> bytes:
    """One page per list of text lines; ``boxes[page]`` holds (rect, rgb) filled rectangles to draw."""
    doc = fitz.open()
    for number, lines in enumerate(pages):
        page = doc.new_page(width=size[0], height=size[1])
        for row, line in enumerate(lines):
            page.insert_text((72, FIRST_LINE_Y + row * LINE_STEP), line, fontsize=12)
        for rect, color in (boxes or {}).get(number, []):
            page.draw_rect(fitz.Rect(rect), color=color, fill=color)
    return doc.tobytes()


def open_pdf(data: bytes) -> fitz.Document:
    return fitz.open("pdf", data)


def change_summary(pair: dict) -> list[tuple[str, str, str]]:
    return [(c["type"], c["oldText"], c["newText"]) for c in pair["changes"] if c["kind"] == "text"]
