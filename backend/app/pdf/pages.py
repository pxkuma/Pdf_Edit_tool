"""Page level operations. Each returns a storage.Mutation describing the change."""

from __future__ import annotations

import pymupdf as fitz

from ..storage import Mutation
from .geometry import from_display_rect

PAPER_SIZES = {
    "a4": (595.0, 842.0),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
    "a3": (842.0, 1191.0),
    "a5": (420.0, 595.0),
}


class PageError(ValueError):
    pass


def _check_pages(doc: fitz.Document, pages: list[int]) -> list[int]:
    unique = sorted(set(pages))
    if not unique:
        raise PageError("No pages selected.")
    if unique[0] < 0 or unique[-1] >= doc.page_count:
        raise PageError("Page number out of range.")
    return unique


def rotate(doc: fitz.Document, pages: list[int], angle: int) -> Mutation:
    if angle % 90:
        raise PageError("Rotation must be a multiple of 90 degrees.")
    targets = _check_pages(doc, pages)
    for index in targets:
        page = doc[index]
        page.set_rotation((page.rotation + angle) % 360)
    return Mutation(changed=frozenset(targets))


def reorder(doc: fitz.Document, order: list[int]) -> Mutation:
    """Select pages in a new order. Allows deleting (omit) and duplicating (repeat)."""
    if not order:
        raise PageError("A document must keep at least one page.")
    if any(not 0 <= index < doc.page_count for index in order):
        raise PageError("Page number out of range.")
    doc.select(order)
    return Mutation(changed=frozenset(), page_map=tuple(order))


def delete(doc: fitz.Document, pages: list[int]) -> Mutation:
    targets = set(_check_pages(doc, pages))
    keep = [i for i in range(doc.page_count) if i not in targets]
    return reorder(doc, keep)


def duplicate(doc: fitz.Document, pages: list[int]) -> Mutation:
    targets = set(_check_pages(doc, pages))
    order: list[int] = []
    for index in range(doc.page_count):
        order.append(index)
        if index in targets:
            order.append(index)
    # fullcopy keeps annotations/links independent, so copy one by one from the end.
    for index in sorted(targets, reverse=True):
        doc.fullcopy_page(index, index + 1)
    page_map = tuple(order)
    changed = frozenset(i for i, src in enumerate(page_map) if i > 0 and page_map[i - 1] == src)
    return Mutation(changed=changed, page_map=page_map)


def insert_blank(doc: fitz.Document, at: int, size: str | None, width: float | None, height: float | None) -> Mutation:
    at = max(0, min(at, doc.page_count))
    if width and height:
        w, h = width, height
    elif size and size.lower() in PAPER_SIZES:
        w, h = PAPER_SIZES[size.lower()]
    else:
        reference = doc[min(at, doc.page_count - 1)].rect
        w, h = reference.width, reference.height
    if not (10 <= w <= 14400 and 10 <= h <= 14400):
        raise PageError("Page size out of range.")
    old = list(range(doc.page_count))
    doc.new_page(at, width=w, height=h)
    return Mutation(changed=frozenset({at}), page_map=tuple(old[:at] + [None] + old[at:]))


def insert_pdf(doc: fitz.Document, payload: bytes, at: int, from_page: int | None = None, to_page: int | None = None) -> Mutation:
    try:
        source = fitz.open(stream=payload)
    except Exception as exc:  # noqa: BLE001
        raise PageError("The inserted file could not be opened.") from exc
    try:
        if source.needs_pass:
            raise PageError("The inserted PDF is password protected.")
        if not source.is_pdf:
            converted = fitz.open("pdf", source.convert_to_pdf())
            source.close()
            source = converted
        at = max(0, min(at, doc.page_count))
        start = from_page if from_page is not None else 0
        end = to_page if to_page is not None else source.page_count - 1
        start, end = max(0, start), min(source.page_count - 1, end)
        if end < start:
            raise PageError("Invalid page range for inserted file.")
        old = list(range(doc.page_count))
        doc.insert_pdf(source, from_page=start, to_page=end, start_at=at)
        added = end - start + 1
    finally:
        source.close()
    page_map = tuple(old[:at] + [None] * added + old[at:])
    return Mutation(changed=frozenset(range(at, at + added)), page_map=page_map)


def insert_image_page(doc: fitz.Document, image: bytes, at: int) -> Mutation:
    try:
        img_doc = fitz.open(stream=image)
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
    except Exception as exc:  # noqa: BLE001
        raise PageError("The image could not be read.") from exc
    return insert_pdf(doc, pdf_bytes, at)


def crop(doc: fitz.Document, pages: list[int], rect: tuple) -> Mutation:
    targets = _check_pages(doc, pages)
    for index in targets:
        page = doc[index]
        local = from_display_rect(page, rect) & fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
        if local.is_empty or local.width < 20 or local.height < 20:
            raise PageError("Crop area is too small.")
        offset = page.cropbox.tl
        page.set_cropbox(local + (offset.x, offset.y, offset.x, offset.y))
    return Mutation(changed=frozenset(targets))


def reset_crop(doc: fitz.Document, pages: list[int]) -> Mutation:
    targets = _check_pages(doc, pages)
    for index in targets:
        page = doc[index]
        page.set_cropbox(page.mediabox)
    return Mutation(changed=frozenset(targets))


def extract(doc: fitz.Document, pages: list[int]) -> bytes:
    targets = _check_pages(doc, pages) if pages else list(range(doc.page_count))
    out = fitz.open()
    try:
        for index in targets:
            out.insert_pdf(doc, from_page=index, to_page=index)
        return out.tobytes(garbage=3, deflate=True)
    finally:
        out.close()


def page_info(doc: fitz.Document) -> list[dict]:
    return [
        {
            "index": index,
            "width": round(page.rect.width, 3),
            "height": round(page.rect.height, 3),
            "rotation": page.rotation,
            "label": page.get_label() if hasattr(page, "get_label") else "",
        }
        for index, page in enumerate(doc)
    ]
