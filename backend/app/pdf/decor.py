"""Underline and strikethrough lines that belong to text runs.

They are separate line paths in the content stream (whoever drew them), so the
editor detects them per run, reports them to the UI (so toggles show their real
state), and erases them when the run is rewritten. The writer then draws them
again at the new text width, only if they are still wanted.
"""

from __future__ import annotations

from collections.abc import Callable

import pymupdf as fitz

from . import push

MAX_THICKNESS = 3.0


def _horizontal(path: dict) -> bool:
    for item in path["items"]:
        if item[0] == "l":
            if abs(item[1].y - item[2].y) > 0.5:
                return False
        elif item[0] == "re":
            if fitz.Rect(item[1]).height > MAX_THICKNESS:
                return False
        else:
            return False
    return True


def page_rules(page: fitz.Page) -> list[dict]:
    """Thin horizontal paths on the page (decoration candidates), unrotated space."""
    return [p for p in page.get_drawings()
            if push.path_rect(p).height <= MAX_THICKNESS + 1 and p["rect"].width >= 2 and _horizontal(p)]


def for_run(run: dict, line_bbox: tuple, direction: tuple, rules: list[dict]) -> dict[str, list[dict]]:
    """Decorations of a run: ``{"underline": [...paths], "strike": [...paths]}``."""
    found: dict[str, list[dict]] = {"underline": [], "strike": []}
    if abs(direction[1]) > 0.01 or direction[0] <= 0:
        return found  # only horizontal, left-to-right text
    x0, _y0, x1, _y1 = run["bbox"]
    size = run["size"]
    baseline = run["origin"][1]
    line_x0, line_x1 = line_bbox[0], line_bbox[2]
    for path in rules:
        rect = fitz.Rect(path["rect"])
        if min(rect.x1, x1) - max(rect.x0, x0) < 0.6 * (x1 - x0):
            continue
        if rect.x0 < line_x0 - size * 0.6 or rect.x1 > line_x1 + size * 0.6:
            continue  # a table rule or separator, not this text's decoration
        offset = (rect.y0 + rect.y1) / 2 - baseline
        if -0.45 * size <= offset <= -0.12 * size:
            found["strike"].append(path)
        elif -0.05 * size <= offset <= 0.35 * size:
            found["underline"].append(path)
    return found


def _same(a: dict, b: dict) -> bool:
    return tuple(a["rect"]) == tuple(b["rect"]) and a.get("color") == b.get("color") and a.get("type") == b.get("type")


def erase(page: fitz.Page, paths: list[dict], redact: Callable) -> None:
    """Remove decoration paths; other paths caught by the removal are put back."""
    if not paths:
        return
    removal = [push.removal_rect(p) for p in paths]
    keep = [p for p in page.get_drawings()
            if not any(_same(p, q) for q in paths)
            and any(push.inside(push.path_rect(p), r + (push.PAD, push.PAD, -push.PAD, -push.PAD)) for r in removal)]
    redact(page, removal, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED, text=fitz.PDF_REDACT_TEXT_NONE)
    if keep:
        shape = page.new_shape()
        for path in keep:
            push.draw_path(shape, path, fitz.Identity)
        shape.commit(overlay=True)
