"""Canva-style image placement: free rotation, opacity, stacking, and image adjustments.

``place_image`` writes the placement itself (a ``q cm [gs] /Name Do Q`` block), because
``Page.insert_image`` only rotates in quarter turns and knows no transparency. The placement
rectangle and angle arrive in display space (rotated page, y-down) like every other edit.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import pymupdf as fitz

from .images import ImageError, delete_image, image_bytes, private_resource_dict, usage_counts

MAX_ADJUST_PIXELS = 80_000_000
MIN_CROP = 0.01  # fractions of the image smaller than this are rejected as empty


@dataclass(frozen=True)
class Adjustments:
    """Pixel adjustments, Canva-style. Neutral values leave the image alone."""

    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    grayscale: bool = False
    flip_h: bool = False
    flip_v: bool = False
    crop: tuple[float, float, float, float] | None = None  # left, top, right, bottom as fractions

    def neutral(self) -> bool:
        return (self.brightness == 1 and self.contrast == 1 and self.saturation == 1
                and not self.grayscale and not self.flip_h and not self.flip_v and self.crop is None)


# ------------------------------------------------------------------ placement
def place_image(doc: fitz.Document, page: fitz.Page, xref: int, rect: tuple,
                angle: float = 0.0, opacity: float = 1.0, overlay: bool = True) -> None:
    """Place image ``xref`` at display-space ``rect``, rotated ``angle`` degrees clockwise.

    Existing placements of the image on this page are removed first, so the call expresses
    the complete state: position, size, rotation, opacity and stacking (``overlay`` False
    puts the image behind the page's other content).
    """
    if xref <= 0:
        raise ImageError("This image is inline and cannot be transformed.")
    target = fitz.Rect(rect)
    target.normalize()
    if target.width < 2 or target.height < 2:
        raise ImageError("Image area is too small.")
    delete_image(page, xref)
    _write_placement(doc, page, xref, target, angle, opacity, overlay)


def _write_placement(doc: fitz.Document, page: fitz.Page, xref: int, rect: fitz.Rect,
                     angle: float, opacity: float, overlay: bool) -> None:
    matrix = _placement_matrix(page, rect, angle)
    name = f"PSim{xref}"
    holder, prefix = private_resource_dict(doc, page, "XObject")
    doc.xref_set_key(holder, f"{prefix}/{name}" if prefix else name, f"{xref} 0 R")
    gs = b""
    if opacity < 1:
        gs_name = f"PSgs{max(1, round(opacity * 100))}"
        gs_holder, gs_prefix = private_resource_dict(doc, page, "ExtGState")
        doc.xref_set_key(gs_holder, f"{gs_prefix}/{gs_name}" if gs_prefix else gs_name,
                         f"<</Type/ExtGState/ca {opacity:.2f}/CA {opacity:.2f}>>")
        gs = f"/{gs_name} gs ".encode()
    block = (b"q " + gs
             + f"{matrix.a:.4f} {matrix.b:.4f} {matrix.c:.4f} {matrix.d:.4f} "
               f"{matrix.e:.4f} {matrix.f:.4f} cm ".encode()
             + f"/{name} Do Q".encode())
    content = page.read_contents()
    merged = content + b" " + block if overlay else block + b" " + content
    stream = doc.get_new_xref()
    doc.update_object(stream, "<<>>")
    doc.update_stream(stream, merged)
    page.set_contents(stream)


def _placement_matrix(page: fitz.Page, rect: fitz.Rect, angle: float) -> fitz.Matrix:
    """Content-stream matrix mapping the image's unit square onto display-space ``rect``
    rotated ``angle`` degrees visually clockwise about the rect center.

    Built in display space (what the user sees, y-down), then taken through the page's
    derotation into MuPDF page space and on into raw PDF content coordinates.
    """
    upright = fitz.Matrix(rect.width, 0, 0, -rect.height, rect.x0, rect.y1)
    theta = math.radians(angle % 360)
    cos, sin = math.cos(theta), math.sin(theta)
    center = ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    about_center = (fitz.Matrix(1, 0, 0, 1, -center[0], -center[1])
                    * fitz.Matrix(cos, sin, -sin, cos, 0, 0)
                    * fitz.Matrix(1, 0, 0, 1, center[0], center[1]))
    return upright * about_center * page.derotation_matrix * page.transformation_matrix


def placement_angle(page: fitz.Page, transform: tuple) -> float:
    """Visual clockwise angle (display space) of a placement's unit-square transform."""
    matrix = fitz.Matrix(transform)
    angle = math.degrees(math.atan2(matrix.b, matrix.a))
    return round((angle + page.rotation) % 360, 1)


# ------------------------------------------------------------------ adjustments
def adjust_image(doc: fitz.Document, page: fitz.Page, xref: int, adjustments: Adjustments) -> None:
    """Bake pixel adjustments into the image behind this page's placement.

    An image object shared with other placements is copied first, so only this page changes.
    """
    if xref <= 0:
        raise ImageError("This image is inline and cannot be adjusted.")
    if adjustments.neutral():
        return
    data, _media = image_bytes(doc, xref)
    adjusted = _apply_adjustments(data, adjustments)
    if usage_counts(doc).get(xref, 1) <= 1:
        page.replace_image(xref, stream=adjusted)
        return
    _swap_page_references(doc, page, xref, adjusted)


def _swap_page_references(doc: fitz.Document, page: fitz.Page, xref: int, adjusted: bytes) -> None:
    """Point this page's references to ``xref`` at a new image object holding ``adjusted``.

    The placements (and their transforms) stay untouched, so rotation and stacking survive;
    other pages keep the original image object.
    """
    names = [item[7] for item in page.get_images(full=True) if item[0] == xref and item[9] == 0]
    if not names:
        raise ImageError("A shared image placed through a Form XObject cannot be adjusted on one page only.")
    info = next((i for i in page.get_image_info(xrefs=True) if i.get("xref") == xref), None)
    if info is None:
        raise ImageError("Image not found on this page.")
    fresh = page.insert_image(fitz.Rect(info["bbox"]), stream=adjusted)
    delete_image(page, fresh)  # keep the object, drop the placement insert_image just made
    holder, prefix = private_resource_dict(doc, page, "XObject")
    for name in names:
        doc.xref_set_key(holder, f"{prefix}/{name}" if prefix else name, f"{fresh} 0 R")


def _apply_adjustments(data: bytes, adjustments: Adjustments) -> bytes:
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError as exc:  # pragma: no cover - Pillow is a declared dependency
        raise ImageError("Image adjustments need the Pillow library.") from exc
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ImageError("This image could not be decoded for adjustment.") from exc
    if img.width * img.height > MAX_ADJUST_PIXELS:
        raise ImageError("Image resolution is too large to adjust.")
    had_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    img = img.convert("RGBA") if had_alpha else img.convert("RGB")
    if adjustments.crop:
        img = _crop(img, adjustments.crop)
    if adjustments.flip_h:
        img = ImageOps.mirror(img)
    if adjustments.flip_v:
        img = ImageOps.flip(img)
    if adjustments.grayscale:
        img = ImageEnhance.Color(img).enhance(0)
    elif adjustments.saturation != 1:
        img = ImageEnhance.Color(img).enhance(adjustments.saturation)
    if adjustments.brightness != 1:
        img = ImageEnhance.Brightness(img).enhance(adjustments.brightness)
    if adjustments.contrast != 1:
        img = ImageEnhance.Contrast(img).enhance(adjustments.contrast)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _crop(img, crop: tuple[float, float, float, float]):
    left, top, right, bottom = crop
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ImageError("Crop fractions must satisfy 0 <= left < right <= 1 (and likewise top/bottom).")
    if right - left < MIN_CROP or bottom - top < MIN_CROP:
        raise ImageError("Crop area is too small.")
    box = (round(left * img.width), round(top * img.height),
           round(right * img.width), round(bottom * img.height))
    if box[2] - box[0] < 1 or box[3] - box[1] < 1:
        raise ImageError("Crop area is too small.")
    return img.crop(box)
