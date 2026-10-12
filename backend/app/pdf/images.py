"""Image placement, replacement and removal."""

from __future__ import annotations

import pymupdf as fitz

from .geometry import from_display_rect, to_display_rect

MAX_IMAGE_BYTES = 40 * 1024 * 1024


class ImageError(ValueError):
    pass


def _validate_image(data: bytes) -> None:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageError("Image is empty or larger than 40 MB.")
    try:
        pix = fitz.Pixmap(data)
    except Exception as exc:  # noqa: BLE001
        raise ImageError("Unsupported image format. Use PNG, JPEG, GIF, BMP, TIFF or WEBP.") from exc
    if pix.width * pix.height > 80_000_000:
        raise ImageError("Image resolution is too large.")


def _normalized_image(data: bytes) -> bytes:
    """MuPDF embeds PNG/JPEG directly; everything else is converted to PNG."""
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    pix = fitz.Pixmap(data)
    if pix.colorspace and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix.tobytes("png")


def insert_image(page: fitz.Page, rect: tuple, data: bytes, keep_proportion: bool = True) -> None:
    _validate_image(data)
    target = from_display_rect(page, rect)
    if target.width < 2 or target.height < 2:
        raise ImageError("Image area is too small.")
    page.insert_image(target, stream=_normalized_image(data), keep_proportion=keep_proportion, rotate=page.rotation)


def _usage_count(doc: fitz.Document, xref: int) -> int:
    count = 0
    for page in doc:
        count += sum(1 for info in page.get_image_info(xrefs=True) if info.get("xref") == xref)
    return count


def list_images(doc: fitz.Document, page: fitz.Page) -> list[dict]:
    items = []
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref", 0)
        bbox = fitz.Rect(info["bbox"]) & fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
        if bbox.is_empty:
            continue
        items.append({
            "xref": xref,
            "bbox": to_display_rect(page, info["bbox"]),
            "width": info.get("width"),
            "height": info.get("height"),
            "editable": xref > 0,
            "uses": _usage_count(doc, xref) if xref > 0 else 1,
        })
    return items


def image_bytes(doc: fitz.Document, xref: int) -> tuple[bytes, str]:
    """Return the image (with transparency applied) as PNG or original JPEG."""
    info = doc.extract_image(xref)
    if not info:
        raise ImageError("Image not found.")
    smask = info.get("smask", 0)
    if not smask and info.get("ext") in ("jpeg", "jpg", "png"):
        return info["image"], "image/png" if info["ext"] == "png" else "image/jpeg"
    pix = fitz.Pixmap(doc, xref)
    if smask:
        try:
            pix = fitz.Pixmap(pix, fitz.Pixmap(doc, smask))
        except Exception:  # noqa: BLE001 - mismatching masks: ignore transparency
            pass
    if pix.colorspace and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix.tobytes("png"), "image/png"


def delete_image(page: fitz.Page, xref: int) -> None:
    if xref <= 0:
        raise ImageError("This image is inline and cannot be removed individually.")
    page.delete_image(xref)


def replace_image(page: fitz.Page, xref: int, data: bytes) -> None:
    if xref <= 0:
        raise ImageError("This image is inline and cannot be replaced.")
    _validate_image(data)
    page.replace_image(xref, stream=_normalized_image(data))


def move_image(doc: fitz.Document, page: fitz.Page, xref: int, rect: tuple) -> None:
    payload, _mime = image_bytes(doc, xref)
    delete_image(page, xref)
    target = from_display_rect(page, rect)
    page.insert_image(target, stream=payload, keep_proportion=False, rotate=page.rotation)
