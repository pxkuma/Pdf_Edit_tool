"""OCR for scanned pages (Tesseract).

Recognised words are written as an *invisible* text layer (render mode 3) placed
exactly over the scanned glyphs: the page looks unchanged but becomes searchable,
selectable and editable. Editing such a word later replaces it in the image (see
``scanned_replacement``).
"""

from __future__ import annotations

import csv
import io
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

import pymupdf as fitz

from .fonts import FontCatalog
from .geometry import from_display_point, from_display_vector
from .textwriter import FontChain, PlacedLine, TextStyle, line_width, write_lines

log = logging.getLogger(__name__)

DESCENDERS = set("gjpqyQ,;()[]{}|/")
ASCENDERS = set("bdfhiklt!?") | set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
OCR_TIMEOUT_SECONDS = 180
MIN_CONFIDENCE = 10.0


class OcrError(RuntimeError):
    pass


def tesseract_path() -> str | None:
    return shutil.which("tesseract")


@lru_cache(maxsize=1)
def languages() -> tuple[str, ...]:
    exe = tesseract_path()
    if not exe:
        return ()
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return ()
    langs = [line.strip() for line in out.stdout.splitlines()[1:] if line.strip() and line.strip() != "osd"]
    return tuple(sorted(langs))


def validate_language(language: str) -> str:
    parts = [p for p in language.split("+") if p]
    available = set(languages())
    if not parts or any(p not in available for p in parts):
        raise OcrError(f"OCR language '{language}' is not installed. Available: {', '.join(sorted(available)) or 'none'}.")
    return "+".join(parts)


@dataclass
class OcrWord:
    text: str
    rect: tuple[float, float, float, float]  # display-space points
    confidence: float


@dataclass
class OcrLine:
    words: list[OcrWord] = field(default_factory=list)
    rect: tuple[float, float, float, float] = (0, 0, 0, 0)


def render_for_ocr(page: fitz.Page, dpi: int) -> tuple[bytes, float]:
    """Render the page as the reader sees it (rotation applied) in grayscale."""
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False, annots=False)
    return pix.tobytes("png"), zoom


def run_tesseract(png: bytes, language: str, dpi: int) -> str:
    exe = tesseract_path()
    if not exe:
        raise OcrError("Tesseract is not installed. Use the Docker image, which includes it.")
    command = [exe, "stdin", "stdout", "-l", language, "--dpi", str(dpi), "--psm", "3", "tsv"]
    try:
        result = subprocess.run(command, input=png, capture_output=True, timeout=OCR_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        raise OcrError("OCR took too long for this page.") from exc
    except OSError as exc:
        raise OcrError("Could not start Tesseract.") from exc
    if result.returncode != 0:
        log.warning("tesseract failed: %s", result.stderr[-500:])
        raise OcrError("OCR failed on this page.")
    return result.stdout.decode("utf-8", errors="replace")


def parse_tsv(tsv: str, zoom: float) -> list[OcrLine]:
    lines: dict[tuple[int, int, int, int], OcrLine] = {}
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        try:
            level = int(row["level"])
            key = (int(row["page_num"]), int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
            left, top, width, height = (float(row[k]) / zoom for k in ("left", "top", "width", "height"))
        except (KeyError, TypeError, ValueError):
            continue
        rect = (left, top, left + width, top + height)
        if level == 4:
            lines.setdefault(key, OcrLine()).rect = rect
        elif level == 5:
            text = (row.get("text") or "").strip()
            confidence = float(row.get("conf") or -1)
            if text and confidence >= MIN_CONFIDENCE:
                lines.setdefault(key, OcrLine(rect=rect)).words.append(OcrWord(text, rect, confidence))
    return [line for line in lines.values() if line.words]


def _line_metrics(line: OcrLine) -> tuple[float, float]:
    """(font size, baseline y) for a recognised line, from its ink extent."""
    text = "".join(word.text for word in line.words)
    top = min(w.rect[1] for w in line.words)
    bottom = max(w.rect[3] for w in line.words)
    has_desc = any(ch in DESCENDERS for ch in text)
    has_asc = any(ch in ASCENDERS for ch in text)
    # Calibrated on Tesseract boxes at 300 dpi (they include anti-aliasing).
    ink = (0.76 if has_asc else 0.54) + (0.2 if has_desc else 0.0)
    size = max(2.0, (bottom - top) / ink)
    baseline = bottom - (0.2 * size if has_desc else 0.0)
    return size, baseline


def write_text_layer(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog, lines: list[OcrLine]) -> int:
    """Write recognised words as invisible text exactly over the scan. Returns word count."""
    face = catalog.substitute("Helvetica", False, False, False, False)
    chain = FontChain.build(catalog, None, face)
    direction = from_display_vector(page, (1.0, 0.0))
    placed: list[PlacedLine] = []
    sizes: list[float] = []
    for line in lines:
        size, baseline = _line_metrics(line)
        for word in line.words:
            glyphs = chain.encode(word.text)
            if not glyphs:
                continue
            natural = line_width(glyphs, TextStyle(size=size))
            target = word.rect[2] - word.rect[0]
            hscale = max(20.0, min(400.0, 100.0 * target / natural)) if natural > 0 else 100.0
            origin = from_display_point(page, (word.rect[0], baseline))
            placed.append(PlacedLine((origin.x, origin.y), direction, glyphs, hscale=hscale, size=size))
            sizes.append(size)
    if not placed:
        return 0
    style = TextStyle(size=sorted(sizes)[len(sizes) // 2], render_mode=3)
    write_lines(doc, page, placed, style, chain)
    return len(placed)


def page_scan_info(page: fitz.Page) -> dict:
    """Is the page a scan (mostly image, little real text) and does it have OCR text?"""
    area = abs(page.rect) or 1.0
    covered = 0.0
    for info in page.get_image_info():
        covered += abs(fitz.Rect(info["bbox"]) & page.rect)
    visible = invisible = 0
    for trace in page.get_texttrace():
        count = len(trace.get("chars", ()))
        if trace.get("type") == 3 or trace.get("opacity", 1) == 0:
            invisible += count
        else:
            visible += count
    return {
        "scanned": covered / area > 0.5 and visible < 25,
        "hasOcr": invisible > 0,
    }


def remove_invisible_text(page: fitz.Page) -> None:
    page.add_redact_annot(page.rect, fill=False)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_REMOVE_INVISIBLE)


# ------------------------------------------------------------------ editing scans
@dataclass(frozen=True)
class ScanSample:
    background: tuple[float, float, float]
    ink: tuple[float, float, float]
    coverage: float  # share of the word box covered by ink

    @property
    def looks_bold(self) -> bool:
        return self.coverage > 0.235


def sample_colors(page: fitz.Page, rect: fitz.Rect) -> ScanSample:
    """Background colour, ink colour and ink coverage of a scanned word."""
    clip = fitz.Rect(rect) * page.rotation_matrix
    clip.normalize()
    clip = (clip + (-2, -2, 2, 2)) & page.rect
    white = ScanSample((1.0, 1.0, 1.0), (0.0, 0.0, 0.0), 0.0)
    if clip.is_empty:
        return white
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, colorspace=fitz.csRGB, alpha=False, annots=False)
    samples = pix.samples
    width, height, n = pix.width, pix.height, pix.n
    pixels = [tuple(samples[i:i + 3]) for i in range(0, len(samples), n)]
    if not pixels:
        return white
    border = [pixels[y * width + x] for y in range(height) for x in range(width)
              if x < 3 or y < 3 or x >= width - 3 or y >= height - 3]
    background = _dominant(border or pixels)
    far = sorted(pixels, key=lambda p: _distance(p, background), reverse=True)
    ink_pixels = [p for p in far[: max(1, len(far) // 8)] if _distance(p, background) > 60]
    ink = tuple(sum(c[i] for c in ink_pixels) / len(ink_pixels) for i in range(3)) if ink_pixels else (0, 0, 0)
    contrast = _distance(ink, background) or 1.0
    inner = [pixels[y * width + x] for y in range(6, height - 6) for x in range(6, width - 6)] or pixels
    coverage = sum(1 for p in inner if _distance(p, background) > contrast * 0.5) / len(inner)
    return ScanSample(tuple(c / 255.0 for c in background), tuple(c / 255.0 for c in ink), coverage)  # type: ignore[arg-type]


def _distance(a: tuple, b: tuple) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _dominant(pixels: list[tuple]) -> tuple:
    buckets: dict[tuple, list[tuple]] = {}
    for p in pixels:
        buckets.setdefault((p[0] // 16, p[1] // 16, p[2] // 16), []).append(p)
    best = max(buckets.values(), key=len)
    return tuple(sum(c[i] for c in best) / len(best) for i in range(3))
