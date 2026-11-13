"""Image placement, replacement and removal."""

from __future__ import annotations

import math
import re
from typing import Callable, Mapping

import pymupdf as fitz

from .geometry import from_display_rect, to_display_point, to_display_rect
from .redaction import redact_areas

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


def usage_counts(doc: fitz.Document) -> dict[int, int]:
    """How many times each image object is placed in the document (one pass over all pages)."""
    counts: dict[int, int] = {}
    for page in doc:
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            if xref > 0:
                counts[xref] = counts.get(xref, 0) + 1
    return counts


def _placement_geometry(page: fitz.Page, transform: fitz.Matrix, bbox: tuple) -> tuple[float, tuple]:
    """Visual clockwise angle and un-rotated display rect of a placement's unit-square transform.

    A placement that is not a plain rotate+scale (sheared, degenerate) reports angle 0 and its bbox.
    """
    width = math.hypot(transform.a, transform.b)
    height = math.hypot(transform.c, transform.d)
    shear = abs(transform.a * transform.c + transform.b * transform.d)
    if width < 0.01 or height < 0.01 or shear > 0.01 * width * height:
        return 0.0, bbox
    angle = round((math.degrees(math.atan2(transform.b, transform.a)) + page.rotation) % 360, 1)
    if angle == 360:
        angle = 0.0
    center = to_display_point(page, (transform.e + (transform.a + transform.c) / 2,
                                     transform.f + (transform.b + transform.d) / 2))
    rect = (round(center[0] - width / 2, 3), round(center[1] - height / 2, 3),
            round(center[0] + width / 2, 3), round(center[1] + height / 2, 3))
    return angle, rect


def _placement_opacity(content: bytes, xref: int) -> float:
    """Opacity of our own placement block for ``xref`` (1.0 for placements we did not write)."""
    match = re.search(rb"/PSgs(\d+) gs [^Q]*?/PSim" + str(xref).encode() + rb" Do", content)
    return int(match.group(1)) / 100 if match else 1.0


_OWN_BLOCK = re.compile(rb"q (?:/PSgs(\d+) gs )?([\d.eE+\- ]+) cm /PSim(\d+) Do Q")


def _transparent_placements(doc: fitz.Document, page: fitz.Page, content: bytes, seen: set[int]) -> list[dict]:
    """Placements MuPDF's image scan leaves out because they are drawn with opacity below 1.

    ``get_image_info`` ignores such images entirely, so the editor would lose them after an
    opacity change. We wrote their placement blocks ourselves, so they can be read back exactly.
    """
    items = []
    for match in _OWN_BLOCK.finditer(content):
        xref = int(match.group(3))
        if xref in seen or not match.group(1) or int(match.group(1)) >= 100:
            continue
        try:
            values = [float(v) for v in match.group(2).split()]
        except ValueError:
            continue
        if len(values) != 6:
            continue
        to_mu = fitz.Matrix(values) * ~page.transformation_matrix
        corners = [fitz.Point(x, y) * to_mu for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))]
        bbox = fitz.Rect(min(p.x for p in corners), min(p.y for p in corners),
                         max(p.x for p in corners), max(p.y for p in corners))
        display_bbox = to_display_rect(page, bbox)
        angle, rect = _placement_geometry(page, to_mu, display_bbox)
        items.append({
            "xref": xref,
            "bbox": display_bbox,
            "rect": rect,
            "angle": angle,
            "opacity": int(match.group(1)) / 100,
            "width": _int_key(doc, xref, "Width"),
            "height": _int_key(doc, xref, "Height"),
            "editable": True,
            "uses": 1,
        })
    return items


def _int_key(doc: fitz.Document, xref: int, key: str) -> int:
    kind, value = doc.xref_get_key(xref, key)
    try:
        return int(value) if kind == "int" else 0
    except ValueError:
        return 0


def list_images(doc: fitz.Document, page: fitz.Page, usage: Callable[[], Mapping[int, int]] | None = None) -> list[dict]:
    """The images placed on ``page``. ``usage`` supplies (cached) document-wide counts when needed."""
    counts: Mapping[int, int] | None = None
    content: bytes | None = None
    items = []
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref", 0)
        bbox = fitz.Rect(info["bbox"]) & fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
        if bbox.is_empty:
            continue
        if xref > 0 and counts is None:
            counts = usage() if usage else usage_counts(doc)
        if content is None:
            content = page.read_contents()
        display_bbox = to_display_rect(page, info["bbox"])
        angle, rect = _placement_geometry(page, fitz.Matrix(info["transform"]), display_bbox)
        items.append({
            "xref": xref,
            "bbox": display_bbox,
            "rect": rect,
            "angle": angle,
            "opacity": _placement_opacity(content, xref) if xref > 0 else 1.0,
            "width": info.get("width"),
            "height": info.get("height"),
            "editable": xref > 0,
            "uses": counts.get(xref, 1) if xref > 0 and counts is not None else 1,
        })
    if content is None:
        content = page.read_contents()
    items += _transparent_placements(doc, page, content, {item["xref"] for item in items})
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
    """Remove every placement of image ``xref`` from ``page`` only.

    The image object itself is left alone: other pages that reuse it keep it (``Page.delete_image``
    would overwrite the shared object and erase it everywhere). Once nothing references it any more,
    the unused object is dropped when the document is saved.
    """
    if xref <= 0:
        raise ImageError("This image is inline and cannot be removed individually.")
    names = _own_resource_names(page, xref)
    if names:
        _unplace(page, names)
    if any(info.get("xref") == xref for info in page.get_image_info(xrefs=True)):
        _redact_placements(page, xref)  # e.g. inside a Form XObject: filtered out of this page's content


def replace_image(page: fitz.Page, xref: int, data: bytes) -> None:
    if xref <= 0:
        raise ImageError("This image is inline and cannot be replaced.")
    _validate_image(data)
    page.replace_image(xref, stream=_normalized_image(data))


def move_image(doc: fitz.Document, page: fitz.Page, xref: int, rect: tuple) -> None:
    """Place image ``xref`` at ``rect`` on ``page`` and remove its old placement(s) on that page.

    The original image object is placed again (no re-encoding), so it stays shared with other pages.
    """
    if xref <= 0:
        raise ImageError("This image is inline and cannot be moved.")
    target = from_display_rect(page, rect)
    delete_image(page, xref)
    page.insert_image(target, xref=xref, keep_proportion=False, rotate=page.rotation)


# ------------------------------------------------------------------ page-local removal
_SIMPLE_NAME = re.compile(r"^[A-Za-z0-9_.+\-]+$")
_MAX_PARENT_DEPTH = 32


def _own_resource_names(page: fitz.Page, xref: int) -> list[str]:
    """Names under which ``page``'s own resources refer to image ``xref`` (not via a Form XObject)."""
    entries = [item for item in page.get_images(full=True) if item[0] == xref and item[9] == 0]
    names = [item[7] for item in entries]
    return names if names and all(_SIMPLE_NAME.match(name) for name in names) else []


def _unplace(page: fitz.Page, names: list[str]) -> None:
    """Copy-on-write: drop ``names`` from this page's resources and content, leaving other pages alone.

    Resources (and the content stream) may be shared with other pages or inherited, so the page first
    gets private copies of them; only those copies are edited.
    """
    doc = page.parent
    holder, prefix = private_resource_dict(doc, page, "XObject")
    content = page.read_contents()
    for name in names:
        content = re.sub(rb"(?<![\w#])/" + re.escape(name.encode()) + rb"\s+Do(?![\w*'\"])", b" ", content)
        doc.xref_set_key(holder, f"{prefix}/{name}" if prefix else name, "null")
    stream = doc.get_new_xref()
    doc.update_object(stream, "<<>>")
    doc.update_stream(stream, content)
    page.set_contents(stream)


def private_resource_dict(doc: fitz.Document, page: fitz.Page, category: str = "XObject") -> tuple[int, str]:
    """Give ``page`` its own /Resources and /<category> dictionaries; return (object, key path) of the latter."""
    holder, prefix = _private_resources(doc, page)
    path = f"{prefix}/{category}" if prefix else category
    kind, value = doc.xref_get_key(holder, path)
    if kind == "xref":
        own = _clone_dict(doc, int(value.split()[0]))
        doc.xref_set_key(holder, path, f"{own} 0 R")
        return own, ""
    if kind == "dict":
        return holder, path
    if kind in ("null", "none"):
        doc.xref_set_key(holder, path, "<<>>")
        return holder, path
    raise ImageError("This page's resources could not be read.")


def _private_resources(doc: fitz.Document, page: fitz.Page) -> tuple[int, str]:
    kind, value = doc.xref_get_key(page.xref, "Resources")
    if kind == "dict":
        return page.xref, "Resources"  # written inside the page object: already private
    text = doc.xref_object(int(value.split()[0]), compressed=True) if kind == "xref" else _inherited_resources(doc, page)
    own = doc.get_new_xref()
    doc.update_object(own, text)
    doc.xref_set_key(page.xref, "Resources", f"{own} 0 R")
    return own, ""


def _inherited_resources(doc: fitz.Document, page: fitz.Page) -> str:
    """The /Resources a page inherits from its page-tree ancestors (as PDF text)."""
    node = page.xref
    for _ in range(_MAX_PARENT_DEPTH):
        kind, value = doc.xref_get_key(node, "Parent")
        if kind != "xref":
            break
        node = int(value.split()[0])
        kind, value = doc.xref_get_key(node, "Resources")
        if kind == "dict":
            return value
        if kind == "xref":
            return doc.xref_object(int(value.split()[0]), compressed=True)
    return "<<>>"


def _clone_dict(doc: fitz.Document, source: int) -> int:
    clone = doc.get_new_xref()
    doc.update_object(clone, doc.xref_object(source, compressed=True))
    return clone


def _redact_placements(page: fitz.Page, xref: int) -> None:
    """Fallback: filter the placements out of this page's content (touches only overlapping images)."""
    rects = [fitz.Rect(info["bbox"]) + (1, 1, -1, -1) for info in page.get_image_info(xrefs=True)
             if info.get("xref") == xref]
    redact_areas(page, [r for r in rects if not r.is_empty], images=fitz.PDF_REDACT_IMAGE_REMOVE,
                 graphics=fitz.PDF_REDACT_LINE_ART_NONE, text=fitz.PDF_REDACT_TEXT_NONE)
