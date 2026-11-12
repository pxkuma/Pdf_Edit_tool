"""Visual comparison: render both pages at the same scale and find the regions whose pixels differ.

No imaging library is needed. Rows that are byte-identical are skipped at C speed, and only the
8x8 tiles inside rows that differ are looked at pixel by pixel. Neighbouring changed tiles are merged
into regions, so a changed word or a replaced picture is one rectangle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator

import pymupdf as fitz

from ..doctools import capped_dpi
from ..geometry import Rect4

TILE = 8
MAX_COMPARE_PIXELS = 8_000_000  # a page pair is compared on a canvas of at most this many pixels
MIN_DPI = 6  # the lowest resolution a poster-sized page is lowered to
MAX_PIXEL_SCANS = 150_000  # tile rows examined pixel by pixel before a page counts as "different everywhere"
MERGE_POINTS = 12.0  # changes closer than this (in points) form one region
PAD_POINTS = 1.5
SENSITIVITY = {  # (largest colour difference ignored, fewest changed pixels that count as a region)
    "low": (96, 12),
    "medium": (40, 6),
    "high": (10, 3),
}


@dataclass(frozen=True)
class Region:
    rect: Rect4  # points, display space of the (top-left aligned) page
    pixels: int  # changed pixels inside


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    rows: tuple[bytes, ...]


def comparison_dpi(sizes: list[tuple[float, float]], dpi: int) -> int:
    """The resolution used for a pair of pages: the requested one, lowered by the export limit and by
    the (tighter) comparison limit so even a poster-sized page stays small."""
    width = max(w for w, _h in sizes)
    height = max(h for _w, h in sizes)
    dpi = capped_dpi(fitz.Rect(0, 0, width, height), max(36, min(150, dpi)))
    pixels = (width * dpi / 72) * (height * dpi / 72)
    if pixels > MAX_COMPARE_PIXELS:
        dpi = int(dpi * math.sqrt(MAX_COMPARE_PIXELS / pixels))
    return max(MIN_DPI, dpi)


def render(page: fitz.Page, dpi: int) -> fitz.Pixmap:
    zoom = dpi / 72
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)


def canvas(pix: fitz.Pixmap, width: int, height: int) -> Canvas:
    """The pixels as rows on a white canvas of the given size (the page sits in the top-left corner)."""
    samples, n = pix.samples, pix.n
    padding = b"\xff" * ((width - pix.width) * n)
    rows = [samples[y * pix.stride:y * pix.stride + pix.width * n] + padding for y in range(min(pix.height, height))]
    rows.extend([b"\xff" * (width * n)] * (height - len(rows)))
    return Canvas(width, height, tuple(rows))


def _tile_hits(one: Canvas, two: Canvas, threshold: int) -> tuple[dict[tuple[int, int], list[int]], bool]:
    """Changed pixels per 8x8 tile as ``[x0, y0, x1, y1, count]``; the flag says the page differs everywhere."""
    n = len(one.rows[0]) // one.width if one.width else 3
    step = TILE * n
    hits: dict[tuple[int, int], list[int]] = {}
    scans = 0
    for y, (row_a, row_b) in enumerate(zip(one.rows, two.rows)):
        if row_a == row_b:
            continue
        for start in range(0, len(row_a), step):
            chunk_a, chunk_b = row_a[start:start + step], row_b[start:start + step]
            if chunk_a == chunk_b:
                continue
            scans += 1
            if scans > MAX_PIXEL_SCANS:
                return hits, True
            tile = hits.setdefault((y // TILE, start // step), [10**9, 10**9, -1, -1, 0])
            for px in range(0, len(chunk_a), n):
                if any(abs(chunk_a[k] - chunk_b[k]) > threshold for k in range(px, px + n)):
                    x = start // n + px // n
                    tile[0], tile[1] = min(tile[0], x), min(tile[1], y)
                    tile[2], tile[3] = max(tile[2], x), max(tile[3], y)
                    tile[4] += 1
    return {key: box for key, box in hits.items() if box[4]}, False


def _components(hits: dict[tuple[int, int], list[int]], reach: int) -> Iterator[list[tuple[int, int]]]:
    """Groups of changed tiles that lie within ``reach`` tiles of each other."""
    seen: set[tuple[int, int]] = set()
    for start in sorted(hits):
        if start in seen:
            continue
        seen.add(start)
        group, stack = [], [start]
        while stack:
            ty, tx = stack.pop()
            group.append((ty, tx))
            for dy in range(-reach, reach + 1):
                for dx in range(-reach, reach + 1):
                    near = (ty + dy, tx + dx)
                    if near in hits and near not in seen:
                        seen.add(near)
                        stack.append(near)
        yield group


def find_regions(one: Canvas, two: Canvas, dpi: int, sensitivity: str = "medium") -> list[Region]:
    """Rectangles (in points) around the places where the two canvases differ, top to bottom."""
    threshold, min_pixels = SENSITIVITY.get(sensitivity, SENSITIVITY["medium"])
    scale = dpi / 72
    hits, everywhere = _tile_hits(one, two, threshold)
    if everywhere:
        whole = (0.0, 0.0, round(one.width / scale, 2), round(one.height / scale, 2))
        return [Region(whole, one.width * one.height)]
    reach = max(1, math.ceil(MERGE_POINTS * scale / TILE))
    regions = []
    for group in _components(hits, reach):
        boxes = [hits[tile] for tile in group]
        pixels = sum(box[4] for box in boxes)
        if pixels < min_pixels:
            continue
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes) + 1, max(b[3] for b in boxes) + 1
        rect = (
            round(max(0.0, x0 / scale - PAD_POINTS), 2), round(max(0.0, y0 / scale - PAD_POINTS), 2),
            round(min(one.width / scale, x1 / scale + PAD_POINTS), 2), round(min(one.height / scale, y1 / scale + PAD_POINTS), 2),
        )
        regions.append(Region(rect, pixels))
    return sorted(regions, key=lambda r: (r.rect[1], r.rect[0]))


def compare_pages(page_a: fitz.Page, page_b: fitz.Page, dpi: int, sensitivity: str) -> tuple[list[Region], int]:
    """Render both pages at one scale and return the changed regions and the dpi that was used."""
    used = comparison_dpi([(p.rect.width, p.rect.height) for p in (page_a, page_b)], dpi)
    pix_a, pix_b = render(page_a, used), render(page_b, used)
    width, height = max(pix_a.width, pix_b.width), max(pix_a.height, pix_b.height)
    return find_regions(canvas(pix_a, width, height), canvas(pix_b, width, height), used, sensitivity), used
