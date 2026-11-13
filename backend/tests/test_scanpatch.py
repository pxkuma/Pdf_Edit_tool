"""The scan appearance engine: inpainting, degradation estimation, patch building."""

from __future__ import annotations

import io
import math
import random

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.pdf import scanpatch

BG = (0.93, 0.91, 0.86)  # aged paper
INK = (0.15, 0.13, 0.12)


def synthetic_scan(blur: float = 1.2, noise: float = 8.0) -> Image.Image:
    """A fake scanned word: textured paper, blurry dark text, scanner noise."""
    rng = random.Random(7)
    img = Image.new("RGB", (240, 60), tuple(int(c * 255) for c in BG))
    draw = ImageDraw.Draw(img)
    draw.text((20, 14), "Invoice 42", fill=tuple(int(c * 255) for c in INK), font=ImageFont.load_default(26))
    img = img.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        pixels = img.load()
        for y in range(img.height):
            for x in range(0, img.width, 2):
                r, g, b = pixels[x, y]
                d = int(rng.gauss(0, noise))
                pixels[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))
    return img


def scanned_page(doc: fitz.Document) -> fitz.Page:
    """A page whose content is one big 'scan' image with a dark word in the middle."""
    page = doc.new_page(width=200, height=100)
    img = synthetic_scan()
    out = io.BytesIO()
    img.save(out, format="PNG")
    page.insert_image(fitz.Rect(0, 0, 200, 100), stream=out.getvalue(), keep_proportion=False)
    return page


def luma_values(img: Image.Image) -> list[int]:
    return list(img.convert("L").getdata())


def test_ink_mask_finds_the_text():
    img = synthetic_scan()
    mask = scanpatch.ink_mask(img, BG, INK)
    coverage = sum(1 for v in mask.getdata() if v) / (mask.width * mask.height)
    assert 0.01 < coverage < 0.5  # some ink, not the whole image


def test_inpaint_removes_the_ink_but_keeps_the_paper():
    img = synthetic_scan()
    mask = scanpatch.ink_mask(img, BG, INK)
    paper = scanpatch.inpaint(img, mask, ink_darker=True)
    darkest = min(luma_values(paper))
    paper_l = int(scanpatch._luma(BG) * 255)
    assert darkest > paper_l - 70  # no text-dark pixels remain
    mean = sum(luma_values(paper)) / (paper.width * paper.height)
    assert abs(mean - paper_l) < 25  # still looks like the same paper


def test_estimate_scales_with_blur():
    sharp = synthetic_scan(blur=0.3)
    soft = synthetic_scan(blur=2.6)
    est_sharp = scanpatch.estimate(sharp, scanpatch.ink_mask(sharp, BG, INK), BG, INK)
    est_soft = scanpatch.estimate(soft, scanpatch.ink_mask(soft, BG, INK), BG, INK)
    assert est_soft.blur > est_sharp.blur


def test_estimate_measures_noise():
    quiet = synthetic_scan(noise=0)
    loud = synthetic_scan(noise=14)
    est_quiet = scanpatch.estimate(quiet, scanpatch.ink_mask(quiet, BG, INK), BG, INK)
    est_loud = scanpatch.estimate(loud, scanpatch.ink_mask(loud, BG, INK), BG, INK)
    assert est_loud.noise > est_quiet.noise + 2


def test_build_patch_replaces_text_and_keeps_texture():
    doc = fitz.open()
    page = scanned_page(doc)
    cover = fitz.Rect(10, 10, 190, 50)

    def draw(_scratch: fitz.Document, scratch_page: fitz.Page) -> None:
        scratch_page.insert_text((12, 30), "Receipt 99", fontsize=13, color=(0, 0, 0))

    patch_png, clip = scanpatch.build_patch(page, cover, BG, INK, draw)
    patch = Image.open(io.BytesIO(patch_png))
    assert patch.width == round(clip.width * scanpatch.ZOOM)
    values = luma_values(patch)
    paper_l = int(scanpatch._luma(BG) * 255)
    assert min(values) < paper_l - 80  # the new ink is there
    # Paper areas keep noise: the patch is not a flat fill.
    top_rows = values[: patch.width * 3]
    mean = sum(top_rows) / len(top_rows)
    std = math.sqrt(sum((v - mean) ** 2 for v in top_rows) / len(top_rows))
    assert std > 1.0
    doc.close()


def test_build_patch_rejects_huge_regions():
    doc = fitz.open()
    page = doc.new_page(width=3000, height=3000)
    with pytest.raises(scanpatch.ScanPatchError):
        scanpatch.region_image(page, fitz.Rect(0, 0, 3000, 3000))
    doc.close()


def test_write_scan_patch_blends_text_into_the_scan(tmp_path):
    from app.pdf.fonts import FontCatalog
    from app.pdf.textedit import SpanEdit, StyleRequest, _write_scan_patch
    from app.pdf.textwriter import TextStyle

    catalog = FontCatalog([__import__("pathlib").Path("/usr/share/fonts")], tmp_path / "cache.json")
    face = catalog.substitute("Helvetica", False, False, False, False)
    if face is None:
        pytest.skip("no substitute font installed")
    doc = fitz.open()
    page = scanned_page(doc)
    cover = fitz.Rect(15, 12, 185, 48)
    edit = SpanEdit(bbox=tuple(cover), origin=(20, 42), original_text="Invoice 42", text="Receipt 7")
    style = TextStyle(size=22, color=INK)
    request = StyleRequest(font=f"face:{face.id}", size=22)
    ok = _write_scan_patch(doc, page, catalog, edit, cover, (20, 42), (1.0, 0.0), style, request, BG)
    assert ok
    # The area shows dark ink again (the replacement), surrounded by paper that is not flat.
    pix = page.get_pixmap(clip=fitz.Rect(15, 12, 185, 48), colorspace=fitz.csRGB, alpha=False)
    values = [pix.samples[i] for i in range(0, len(pix.samples), 3)]
    assert min(values) < 120
    corner = page.get_pixmap(clip=fitz.Rect(0, 0, 12, 10), colorspace=fitz.csRGB, alpha=False)
    corner_values = [corner.samples[i] for i in range(0, len(corner.samples), 3)]
    assert max(corner_values) - min(corner_values) > 2  # texture, not a flat fill
    # The real text is there, but invisible (search finds it).
    assert page.search_for("Receipt 7")
    doc.close()


def test_degrade_alpha_softens_and_caps_ink():
    crisp = Image.new("L", (120, 40), 0)
    draw = ImageDraw.Draw(crisp)
    draw.rectangle((20, 10, 100, 30), fill=255)
    out = scanpatch.degrade_alpha(crisp, scanpatch.Degradation(blur=1.5, noise=6, ink_alpha=0.8))
    values = list(out.getdata())
    assert max(values) <= int(0.8 * 255)  # ink never reaches full density
    edges = sum(1 for v in values if 20 < v < 180)
    assert edges > 30  # soft edges exist
