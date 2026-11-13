"""Natural-looking text edits inside scanned pages.

Instead of covering the old word with a flat rectangle and drawing crisp vector
text (which screams "edited"), this module rebuilds the patch the way the scanner
would have seen it:

1. the paper behind the word is reconstructed from the surrounding texture
   (morphological inpainting, so stains, gradients and noise survive);
2. the replacement text is rasterised and then degraded to match the scan:
   the blur, ink density and noise are estimated from the original word;
3. the finished patch is placed as an image, and the real text is written
   invisibly underneath so search and copy still work.

Everything runs on Pillow only (no GPU, no model downloads). The functions are
small and pure so a learned appearance model can replace single stages later.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import pymupdf as fitz

ZOOM = 3.0  # patch resolution relative to page points (≈216 dpi)
PAD = 2.0  # page points sampled around the word for texture and statistics
MAX_PATCH_PIXELS = 12_000_000


class ScanPatchError(RuntimeError):
    pass


def _pil():
    try:
        from PIL import Image, ImageFilter
    except ImportError as exc:  # pragma: no cover - Pillow is a declared dependency
        raise ScanPatchError("Scanned-text editing needs the Pillow library.") from exc
    return Image, ImageFilter


@dataclass(frozen=True)
class Degradation:
    """How the scanner degraded the original word, estimated from its pixels."""

    blur: float  # gaussian radius, patch pixels
    noise: float  # paper noise sigma, 0-255
    ink_alpha: float  # peak ink density (light scans never reach full ink)


# ------------------------------------------------------------------ analysis
def region_image(page: fitz.Page, rect: fitz.Rect):
    """The page pixels under ``rect`` (MuPDF page space) at patch resolution."""
    Image, _ = _pil()
    clip = patch_clip(page, rect)
    if clip.is_empty:
        raise ScanPatchError("The edited area is outside the page.")
    if clip.width * clip.height * ZOOM * ZOOM > MAX_PATCH_PIXELS:
        raise ScanPatchError("The edited area is too large for scanned-text editing.")
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=clip, colorspace=fitz.csRGB, alpha=False, annots=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), bytes(pix.samples))
    return img, clip


def ink_mask(img, background: tuple[float, float, float], ink: tuple[float, float, float]):
    """Where the ink is, as an L-mode image (255 = ink)."""
    Image, ImageFilter = _pil()
    bg = tuple(int(c * 255) for c in background)
    contrast = max(1.0, _distance(tuple(int(c * 255) for c in ink), bg))
    gray = img.convert("L")
    bg_l = (bg[0] * 299 + bg[1] * 587 + bg[2] * 114) // 1000
    threshold = contrast * 0.3  # generous: blur washes thin strokes far toward the paper colour
    if _luma(ink) <= _luma(background):  # dark ink on light paper
        mask = gray.point(lambda v: 255 if bg_l - v > threshold else 0)
    else:
        mask = gray.point(lambda v: 255 if v - bg_l > threshold else 0)
    return mask.filter(ImageFilter.MaxFilter(3))  # grow one pixel so antialiased edges count as ink


def inpaint(img, mask, ink_darker: bool):
    """Fill the masked ink with the surrounding paper texture."""
    _Image, ImageFilter = _pil()
    # Morphological close in the ink direction removes the strokes but keeps the paper.
    size = 9
    opened = img.filter(ImageFilter.MaxFilter(size)) if ink_darker else img.filter(ImageFilter.MinFilter(size))
    background = opened.filter(ImageFilter.GaussianBlur(2.5))
    soft = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    out = img.copy()
    out.paste(background, (0, 0), soft)
    return out


def estimate(img, mask, background: tuple[float, float, float], ink: tuple[float, float, float]) -> Degradation:
    """Blur, noise and ink density of the original word."""
    bg255 = tuple(int(c * 255) for c in background)
    contrast = max(1.0, _distance(tuple(int(c * 255) for c in ink), bg255))
    gray = img.convert("L")
    gray_pixels = list(gray.getdata())
    mask_pixels = list(mask.getdata())
    bg_l = _luma(background) * 255
    ink_l = _luma(ink) * 255
    span = max(8.0, abs(bg_l - ink_l))
    midtones = edges = 0
    bg_values = []
    for value, masked in zip(gray_pixels, mask_pixels):
        t = (bg_l - value) / span if ink_l <= bg_l else (value - bg_l) / span
        if masked:
            edges += 1
            if 0.2 < t < 0.8:
                midtones += 1
        elif abs(t) < 0.2:
            bg_values.append(value)
    softness = midtones / edges if edges else 0.3
    blur = min(2.6, max(0.5, 0.4 + softness * 3.2))
    if len(bg_values) > 16:
        mean = sum(bg_values) / len(bg_values)
        noise = min(18.0, math.sqrt(sum((v - mean) ** 2 for v in bg_values) / len(bg_values)))
    else:
        noise = 4.0
    ink_alpha = min(1.0, max(0.55, contrast / 230.0 + 0.25))
    return Degradation(blur=blur, noise=noise, ink_alpha=ink_alpha)


# ------------------------------------------------------------------ synthesis
def degrade_alpha(alpha, degradation: Degradation):
    """Make a crisp text alpha channel look scanned: soften edges, vary the ink."""
    Image, ImageFilter = _pil()
    out = alpha.filter(ImageFilter.GaussianBlur(degradation.blur))
    peak = int(degradation.ink_alpha * 255)
    out = out.point(lambda v: min(peak, v))
    if degradation.noise > 0.5:
        # Ink density varies with the paper: modulate the alpha with low-frequency noise.
        grain = Image.effect_noise(out.size, max(8.0, degradation.noise * 3)).filter(ImageFilter.GaussianBlur(1))
        out = Image.composite(out.point(lambda v: int(v * 0.82)), out, grain.point(lambda v: 255 if v > 150 else 0))
    return out


def paper_noise(img, degradation: Degradation, mask):
    """Put scanner noise back where the inpaint smoothed it away."""
    Image, ImageFilter = _pil()
    if degradation.noise < 1.0:
        return img
    sigma = degradation.noise
    noise = Image.effect_noise(img.size, sigma * 2).convert("L")
    flat = Image.new("L", img.size, 128)
    delta = Image.merge("RGB", [noise, noise, noise])
    base = Image.merge("RGB", [flat, flat, flat])
    noisy = _add_signed(img, delta, base)
    soft = mask.filter(ImageFilter.GaussianBlur(1.0))
    out = img.copy()
    out.paste(noisy, (0, 0), soft)
    return out


def _add_signed(img, delta, base):
    from PIL import ImageChops

    return ImageChops.add(ImageChops.subtract(img, base, 1, 0), delta, 1, 0)


def compose(background_img, alpha, ink: tuple[float, float, float]):
    """The degraded text over the reconstructed paper."""
    Image, _ = _pil()
    ink_img = Image.new("RGB", background_img.size, tuple(int(c * 255) for c in ink))
    return Image.composite(ink_img, background_img, alpha)


def patch_clip(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    """The page area a patch for ``rect`` covers (the rect plus sampled padding)."""
    return (fitz.Rect(rect) + (-PAD, -PAD, PAD, PAD)) & page.rect


def rasterize_text(draw, clip: fitz.Rect):
    """Alpha channel of text drawn by ``draw(scratch_doc, scratch_page)`` on a transparent page."""
    Image, _ = _pil()
    scratch = fitz.open()
    try:
        page = scratch.new_page(width=max(4.0, clip.width), height=max(4.0, clip.height))
        draw(scratch, page)
        pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=True)
        rgba = Image.frombytes("RGBA", (pix.width, pix.height), bytes(pix.samples))
        return rgba.getchannel("A")
    finally:
        scratch.close()


def build_patch(page: fitz.Page, rect: fitz.Rect, background: tuple[float, float, float],
                ink: tuple[float, float, float], draw) -> tuple[bytes, fitz.Rect]:
    """The finished patch (PNG bytes) and the page rect it covers.

    ``draw(scratch_doc, scratch_page)`` writes the replacement text onto a scratch page the
    same size as the patch, positioned relative to the patch origin.
    """
    Image, _ = _pil()
    img, clip = region_image(page, rect)
    mask = ink_mask(img, background, ink)
    degradation = estimate(img, mask, background, ink)
    ink_darker = _luma(ink) <= _luma(background)
    paper = inpaint(img, mask, ink_darker)
    paper = paper_noise(paper, degradation, mask)
    crisp = rasterize_text(draw, clip)
    if crisp.size != paper.size:
        crisp = crisp.resize(paper.size)
    alpha = degrade_alpha(crisp, degradation)
    patch = compose(paper, alpha, ink)
    out = io.BytesIO()
    patch.save(out, format="PNG")
    return out.getvalue(), clip


def _distance(a: tuple, b: tuple) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _luma(color: tuple[float, float, float]) -> float:
    return 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
