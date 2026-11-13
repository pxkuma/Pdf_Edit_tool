"""Draw the visible appearance of a digital signature as a one-page PDF.

pyHanko imports that page as the field's appearance stream. The page has the field's size in
unrotated PDF space; on a rotated page the content is drawn turned so that it reads upright on screen.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf as fitz

MIN_FONT = 4.0
MAX_FONT = 14.0
PADDING = 3.0
TEXT_COLOR = (0.1, 0.1, 0.12)


class AppearanceError(ValueError):
    pass


@dataclass(frozen=True)
class AppearanceSpec:
    width: float  # display (on-screen) width of the box, in points
    height: float
    rotation: int  # page rotation: 0, 90, 180 or 270
    lines: tuple[str, ...]
    image: bytes | None = None
    fontfile: str | None = None


def _layout(width: float, height: float, has_image: bool, has_text: bool) -> tuple[fitz.Rect | None, fitz.Rect | None]:
    """Split the box (display space) into an image area and a text area."""
    box = fitz.Rect(0, 0, width, height) + (PADDING, PADDING, -PADDING, -PADDING)
    if not has_image:
        return None, box
    if not has_text:
        return box, None
    if width >= height * 1.6:  # wide box: image left, text right
        split = box.x0 + box.width * 0.45
        return fitz.Rect(box.x0, box.y0, split - PADDING, box.y1), fitz.Rect(split, box.y0, box.x1, box.y1)
    split = box.y0 + box.height * 0.5  # tall box: image on top
    return fitz.Rect(box.x0, box.y0, box.x1, split - PADDING), fitz.Rect(box.x0, split, box.x1, box.y1)


def _unrotate(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    result = fitz.Rect(rect) * page.derotation_matrix
    result.normalize()
    return result


def _check_image(data: bytes) -> None:
    try:
        pix = fitz.Pixmap(data)
    except Exception as exc:  # noqa: BLE001 - MuPDF raises generic errors for bad images
        raise AppearanceError("The signature image could not be read. Use a PNG or JPEG image.") from exc
    if pix.width < 1 or pix.height < 1:
        raise AppearanceError("The signature image is empty.")


def _start_size(text: str, width: float, height: float, font: fitz.Font) -> float:
    """Largest size at which every line fits the box without wrapping."""
    lines = text.split("\n")
    widest = max(font.text_length(line, fontsize=1) for line in lines) or 1.0
    return min(MAX_FONT, height / (len(lines) * 1.25), width / widest)


def _fit_text(page: fitz.Page, rect: fitz.Rect, text: str, fontname: str, rotation: int, font: fitz.Font) -> None:
    turned = rotation in (90, 270)
    width, height = (rect.height, rect.width) if turned else (rect.width, rect.height)
    size = max(MIN_FONT, _start_size(text, width - 1, height, font))
    while size >= MIN_FONT:
        if page.insert_textbox(rect, text, fontname=fontname, fontsize=size, color=TEXT_COLOR, rotate=rotation) >= 0:
            return
        size -= 0.5
    # Too small to fit even at the minimum size: show what fits of the first lines.
    page.insert_textbox(rect, text.split("\n")[0], fontname=fontname, fontsize=MIN_FONT, color=TEXT_COLOR, rotate=rotation)


def build_appearance(spec: AppearanceSpec) -> bytes:
    if spec.rotation not in (0, 90, 180, 270):
        raise AppearanceError("Unsupported page rotation.")
    if spec.image:
        _check_image(spec.image)
    text = "\n".join(line for line in spec.lines if line)
    turned = spec.rotation in (90, 270)
    doc = fitz.open()
    try:
        page = doc.new_page(width=spec.height if turned else spec.width, height=spec.width if turned else spec.height)
        page.set_rotation(spec.rotation)
        image_area, text_area = _layout(spec.width, spec.height, bool(spec.image), bool(text))
        if image_area is not None and spec.image:
            target = _unrotate(page, image_area)
            page.insert_image(target, stream=spec.image, keep_proportion=True, rotate=spec.rotation)
        if text_area is not None and text:
            fontname, font = "helv", fitz.Font("helv")
            if spec.fontfile:
                fontname, font = "SigFont", fitz.Font(fontfile=spec.fontfile)
                page.insert_font(fontname=fontname, fontfile=spec.fontfile)
            _fit_text(page, _unrotate(page, text_area), text, fontname, spec.rotation, font)
        page.set_rotation(0)
        try:
            doc.subset_fonts()
        except Exception:  # noqa: BLE001 - subsetting only makes the file smaller
            pass
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
