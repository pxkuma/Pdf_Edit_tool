"""Conversions between *display* space (what the user sees: rotated page, y-down)
and MuPDF's unrotated page space used by text extraction and insertion."""

from __future__ import annotations

import math

import pymupdf as fitz

Rect4 = tuple[float, float, float, float]


def to_display_rect(page: fitz.Page, rect: fitz.Rect | Rect4) -> Rect4:
    r = fitz.Rect(rect) * page.rotation_matrix
    r.normalize()
    return (round(r.x0, 3), round(r.y0, 3), round(r.x1, 3), round(r.y1, 3))


def to_display_point(page: fitz.Page, point: tuple[float, float]) -> tuple[float, float]:
    p = fitz.Point(point) * page.rotation_matrix
    return (round(p.x, 3), round(p.y, 3))


def to_display_vector(page: fitz.Page, vector: tuple[float, float]) -> tuple[float, float]:
    return _rotate_vector(page.rotation_matrix, vector)


def from_display_rect(page: fitz.Page, rect: Rect4) -> fitz.Rect:
    r = fitz.Rect(rect) * page.derotation_matrix
    r.normalize()
    return r


def from_display_point(page: fitz.Page, point: tuple[float, float]) -> fitz.Point:
    return fitz.Point(point) * page.derotation_matrix


def from_display_vector(page: fitz.Page, vector: tuple[float, float]) -> tuple[float, float]:
    return _rotate_vector(page.derotation_matrix, vector)


def _rotate_vector(matrix: fitz.Matrix, vector: tuple[float, float]) -> tuple[float, float]:
    x = vector[0] * matrix.a + vector[1] * matrix.c
    y = vector[0] * matrix.b + vector[1] * matrix.d
    norm = math.hypot(x, y) or 1.0
    return (round(x / norm, 6), round(y / norm, 6))


def shrink_for_redaction(rect: fitz.Rect, direction: tuple[float, float]) -> fitz.Rect:
    """Shrink a text bbox so that redaction only hits the glyphs of this line.

    MuPDF removes every character whose box *intersects* the redaction rectangle,
    so we keep only the inner band of the line to avoid touching neighbours.
    """
    horizontal = abs(direction[0]) >= abs(direction[1])
    if horizontal:
        band = rect.height * 0.28
        inset = min(0.4, rect.width * 0.1)
        return fitz.Rect(rect.x0 + inset, rect.y0 + band, rect.x1 - inset, rect.y1 - band)
    band = rect.width * 0.28
    inset = min(0.4, rect.height * 0.1)
    return fitz.Rect(rect.x0 + band, rect.y0 + inset, rect.x1 - band, rect.y1 - inset)


def color_to_hex(value: int | float | tuple | list | None) -> str:
    if value is None:
        return "#000000"
    if isinstance(value, (tuple, list)):
        comps = list(value)
        if len(comps) == 1:
            comps = comps * 3
        if len(comps) == 4:  # CMYK
            c, m, y, k = comps
            comps = [(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)]
        return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in comps[:3])
    return f"#{int(value) & 0xFFFFFF:06x}"


def hex_to_rgb(value: str | None, default: tuple[float, float, float] = (0, 0, 0)) -> tuple[float, float, float]:
    if not value:
        return default
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return default
    try:
        return tuple(int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return default
