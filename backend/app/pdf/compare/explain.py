"""Telling a changed picture from a changed word, when both comparisons are run.

A word that was edited also changes pixels. Such a visual region is *explained* by the text change and
is not listed twice. A region that touches an image, or that is not on a text change, is a real visual
difference (a picture, a graphic, text that only moved).
"""

from __future__ import annotations

from typing import Sequence

from ..geometry import Rect4

NEAR_POINTS = 3.0  # how far from a changed word a region may start
IMAGE_SHARE = 0.25  # a region this much on a picture is a picture change
BAND_SHARE = 0.85  # share of the region's height that must lie on the lines of changed words


def _inflate(rect: Rect4, amount: float) -> Rect4:
    return (rect[0] - amount, rect[1] - amount, rect[2] + amount, rect[3] + amount)


def _overlap_area(one: Rect4, two: Rect4) -> float:
    width = min(one[2], two[2]) - max(one[0], two[0])
    height = min(one[3], two[3]) - max(one[1], two[1])
    return width * height if width > 0 and height > 0 else 0.0


def _touches(one: Rect4, two: Rect4) -> bool:
    return one[0] <= two[2] and two[0] <= one[2] and one[1] <= two[3] and two[1] <= one[3]


def _covered_height(rect: Rect4, bands: Sequence[Rect4]) -> float:
    spans = sorted((max(rect[1], b[1]), min(rect[3], b[3])) for b in bands if b[3] > rect[1] and b[1] < rect[3])
    covered, reached = 0.0, rect[1]
    for start, end in spans:
        start = max(start, reached)
        if end > start:
            covered += end - start
            reached = end
    return covered


def explained_by_text(region: Rect4, text_rects: Sequence[Rect4], image_rects: Sequence[Rect4]) -> bool:
    """The region is just the footprint of edited words: it starts at a text change, lies on its lines and is not a picture."""
    near = [_inflate(rect, NEAR_POINTS) for rect in text_rects]
    if not any(_touches(region, rect) for rect in near):
        return False
    area = max(1e-6, (region[2] - region[0]) * (region[3] - region[1]))
    if sum(_overlap_area(region, image) for image in image_rects) >= IMAGE_SHARE * area:
        return False
    height = max(1e-6, region[3] - region[1])
    return _covered_height(region, near) >= BAND_SHARE * height
