"""Rotated/transparent image placement and pixel adjustments (imagestyle.py)."""

from __future__ import annotations

import io

import pymupdf as fitz
import pytest

from app.pdf import imagestyle
from app.pdf.images import ImageError, list_images
from app.pdf.imagestyle import Adjustments


def two_tone_png() -> bytes:
    """A 40x20 image: left half red, right half blue (asymmetric, to verify rotation direction)."""
    from PIL import Image

    img = Image.new("RGB", (40, 20), "#0000ff")
    img.paste((255, 0, 0), (0, 0, 20, 20))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def doc():
    document = fitz.open()
    document.new_page(width=400, height=300)
    yield document
    document.close()


def place_sample(doc, rect=(100, 100, 200, 150)) -> int:
    return doc[0].insert_image(fitz.Rect(rect), stream=two_tone_png())


def pixel(page: fitz.Page, x: float, y: float) -> tuple:
    pix = page.get_pixmap(clip=fitz.Rect(x - 1, y - 1, x + 1, y + 1), alpha=False)
    return pix.pixel(1, 1)


def reddish(rgb: tuple) -> bool:
    return rgb[0] > 150 and rgb[2] < 100


def bluish(rgb: tuple) -> bool:
    return rgb[2] > 150 and rgb[0] < 100


def test_place_without_rotation_matches_rect(doc):
    xref = place_sample(doc)
    imagestyle.place_image(doc, doc[0], xref, (50, 60, 250, 160))
    info = list_images(doc, doc[0])
    assert len(info) == 1
    assert info[0]["bbox"] == pytest.approx((50, 60, 250, 160), abs=0.6)
    assert info[0]["angle"] == 0
    assert reddish(pixel(doc[0], 60, 110)) and bluish(pixel(doc[0], 240, 110))


def test_rotation_90_clockwise_puts_red_at_the_top(doc):
    xref = place_sample(doc)
    imagestyle.place_image(doc, doc[0], xref, (100, 50, 200, 250), angle=90)
    # Rotated 90 degrees clockwise about the center (150, 150), the rect's footprint
    # becomes (50, 100)-(250, 200) and the red (left) half faces up.
    assert reddish(pixel(doc[0], 150, 115)) and bluish(pixel(doc[0], 150, 185))
    assert list_images(doc, doc[0])[0]["angle"] == pytest.approx(90, abs=0.5)


def test_rotation_round_trips_through_list_images(doc):
    xref = place_sample(doc)
    imagestyle.place_image(doc, doc[0], xref, (100, 100, 220, 180), angle=30)
    info = list_images(doc, doc[0])[0]
    assert info["angle"] == pytest.approx(30, abs=0.5)
    assert info["rect"] == pytest.approx((100, 100, 220, 180), abs=0.6)  # the un-rotated rect


def test_opacity_round_trips_through_list_images(doc):
    xref = place_sample(doc)
    imagestyle.place_image(doc, doc[0], xref, (100, 100, 200, 150), angle=15, opacity=0.35)
    assert list_images(doc, doc[0])[0]["opacity"] == pytest.approx(0.35)


def test_opacity_blends_with_the_page(doc):
    xref = place_sample(doc)
    imagestyle.place_image(doc, doc[0], xref, (100, 100, 200, 150), opacity=0.4)
    rgb = pixel(doc[0], 110, 125)  # 40% red over white paper: pink, not pure red
    assert rgb[0] > 200 and rgb[1] > 100 and rgb[2] > 100


def test_send_behind_existing_content(doc):
    page = doc[0]
    page.draw_rect(fitz.Rect(100, 100, 200, 150), color=None, fill=(0, 1, 0))  # green patch
    xref = place_sample(doc, rect=(120, 110, 180, 140))
    imagestyle.place_image(doc, page, xref, (120, 110, 180, 140), overlay=False)
    rgb = pixel(page, 150, 125)  # the green patch stays on top
    assert rgb[1] > 150 and rgb[0] < 100


def test_place_rejects_inline_images(doc):
    with pytest.raises(ImageError):
        imagestyle.place_image(doc, doc[0], 0, (10, 10, 100, 100))


def test_adjust_grayscale(doc):
    xref = place_sample(doc)
    imagestyle.adjust_image(doc, doc[0], xref, Adjustments(grayscale=True))
    rgb = pixel(doc[0], 110, 125)
    assert abs(rgb[0] - rgb[1]) < 12 and abs(rgb[1] - rgb[2]) < 12


def test_adjust_flip_horizontal_swaps_halves(doc):
    xref = place_sample(doc)
    imagestyle.adjust_image(doc, doc[0], xref, Adjustments(flip_h=True))
    assert bluish(pixel(doc[0], 110, 125)) and reddish(pixel(doc[0], 190, 125))


def test_adjust_crop_keeps_only_the_left_half(doc):
    xref = place_sample(doc)
    imagestyle.adjust_image(doc, doc[0], xref, Adjustments(crop=(0.0, 0.0, 0.5, 1.0)))
    assert reddish(pixel(doc[0], 110, 125)) and reddish(pixel(doc[0], 190, 125))


def test_adjust_shared_image_only_touches_this_page(doc):
    page_two = doc.new_page(width=400, height=300)
    xref = place_sample(doc)
    page_two.insert_image(fitz.Rect(100, 100, 200, 150), xref=xref)
    imagestyle.adjust_image(doc, doc[0], xref, Adjustments(grayscale=True))
    first = pixel(doc[0], 110, 125)
    assert abs(first[0] - first[2]) < 12  # page 1: gray
    assert reddish(pixel(page_two, 110, 125))  # page 2: untouched


def test_adjust_rejects_empty_crop(doc):
    xref = place_sample(doc)
    with pytest.raises(ImageError):
        imagestyle.adjust_image(doc, doc[0], xref, Adjustments(crop=(0.5, 0.0, 0.5, 1.0)))


def test_rotated_page_placement_matches_display_rect():
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.set_rotation(90)
    xref = page.insert_image(fitz.Rect(50, 50, 150, 100), stream=two_tone_png())
    imagestyle.place_image(doc, page, xref, (30, 40, 130, 90))  # display-space rect
    assert list_images(doc, page)[0]["bbox"] == pytest.approx((30, 40, 130, 90), abs=0.6)
    doc.close()
