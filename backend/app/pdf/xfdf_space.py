"""Page space as XFDF (and PDF) sees it: y up, unrotated, relative to the page's own origin.

MuPDF annotation coordinates are y-down. This converts between the two.
"""

from __future__ import annotations

import pymupdf as fitz


def number_text(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


class PageSpace:
    def __init__(self, page: fitz.Page) -> None:
        self._to_pdf = ~page.transformation_matrix
        self._to_mupdf = page.transformation_matrix

    # -- MuPDF -> PDF
    def pdf_point(self, point: tuple[float, float]) -> tuple[float, float]:
        mapped = fitz.Point(point) * self._to_pdf
        return mapped.x, mapped.y

    def pdf_point_text(self, point: tuple[float, float]) -> str:
        return ",".join(number_text(v) for v in self.pdf_point(point))

    def pdf_rect_text(self, rect: fitz.Rect) -> str:
        corners = [self.pdf_point((rect.x0, rect.y0)), self.pdf_point((rect.x1, rect.y1))]
        xs, ys = [c[0] for c in corners], [c[1] for c in corners]
        return ",".join(number_text(v) for v in (min(xs), min(ys), max(xs), max(ys)))

    def pdf_points_text(self, points: list) -> str:
        return ";".join(self.pdf_point_text(p) for p in points)

    # -- PDF -> MuPDF
    def point(self, point: tuple[float, float]) -> fitz.Point:
        return fitz.Point(point) * self._to_mupdf

    def rect(self, rect: tuple[float, float, float, float]) -> fitz.Rect:
        a, b = self.point((rect[0], rect[1])), self.point((rect[2], rect[3]))
        return fitz.Rect(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))
