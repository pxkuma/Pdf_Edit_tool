"""Builds the page model consumed by the editor UI (all coordinates in display space)."""

from __future__ import annotations

import pymupdf as fitz

from . import pdfobj
from .fontres import TAG_KEY, clean_font_name, normalize_font_name
from .geometry import color_to_hex, to_display_point, to_display_rect, to_display_vector

TEXT_FLAGS = (
    fitz.TEXT_PRESERVE_LIGATURES
    | fitz.TEXT_PRESERVE_WHITESPACE
    | fitz.TEXT_MEDIABOX_CLIP
)

FLAG_ITALIC = 2
FLAG_SERIF = 4
FLAG_MONO = 8
FLAG_BOLD = 16


def page_dict(page: fitz.Page) -> dict:
    return page.get_text("dict", flags=TEXT_FLAGS)


def span_style_flags(span: dict) -> dict:
    flags = span.get("flags", 0)
    name = span.get("font", "").lower()
    return {
        "bold": bool(flags & FLAG_BOLD) or "bold" in name or "black" in name,
        "italic": bool(flags & FLAG_ITALIC) or "italic" in name or "oblique" in name,
        "serif": bool(flags & FLAG_SERIF),
        "mono": bool(flags & FLAG_MONO),
    }


def _span_model(page: fitz.Page, span: dict, span_id: str, direction: tuple[float, float]) -> dict:
    return {
        "id": span_id,
        "text": span["text"],
        "bbox": to_display_rect(page, span["bbox"]),
        "origin": to_display_point(page, span["origin"]),
        "dir": to_display_vector(page, direction),
        "size": round(span["size"], 2),
        "font": clean_font_name(span["font"]),
        "color": color_to_hex(span.get("color")),
        "opacity": round(span.get("alpha", 255) / 255.0, 3),
        **span_style_flags(span),
    }


# ----------------------------------------------------------------- runs
def tagged_font_names(page: fitz.Page) -> set[str]:
    """Normalized names of fallback fonts inserted by this editor on the page."""
    doc = page.parent
    names: set[str] = set()
    for xref, _ext, _type, basefont, *_ in page.get_fonts(full=True):
        if xref > 0 and pdfobj.get_key(doc, xref, TAG_KEY)[0] != "null":
            names.add(normalize_font_name(basefont))
    return names


def _advance_gap(previous: fitz.Rect, current: fitz.Rect, direction: tuple[float, float]) -> float:
    if abs(direction[0]) >= abs(direction[1]):
        return (current.x0 - previous.x1) if direction[0] > 0 else (previous.x0 - current.x1)
    return (current.y0 - previous.y1) if direction[1] > 0 else (previous.y0 - current.y1)


def _joinable(run: dict, span: dict, tagged: set[str], direction: tuple[float, float]) -> bool:
    size = run["size"]
    if abs(span["size"] - size) > max(0.05 * size, 0.1) or span.get("color") != run.get("color"):
        return False
    gap = _advance_gap(fitz.Rect(run["bbox"]), fitz.Rect(span["bbox"]), direction)
    if gap > 0.3 * size or gap < -0.5 * size:
        return False
    name = normalize_font_name(span["font"])
    return (
        span["text"].isspace()
        or name in tagged
        or name == normalize_font_name(run["font"])
        or run["primary_tagged"]
    )


def _start_run(span: dict, tagged: set[str]) -> dict:
    is_tagged = normalize_font_name(span["font"]) in tagged
    return {**span, "parts": [span], "primary_tagged": is_tagged, "primary_text": "" if is_tagged else span["text"]}


def _extend_run(run: dict, span: dict, tagged: set[str]) -> dict:
    is_tagged = normalize_font_name(span["font"]) in tagged
    merged = {**run, "text": run["text"] + span["text"], "bbox": tuple(fitz.Rect(run["bbox"]) | fitz.Rect(span["bbox"])),
              "parts": run["parts"] + [span]}
    if not is_tagged:
        merged["primary_text"] = run["primary_text"] + span["text"]
        if run["primary_tagged"]:
            # The run began with fallback glyphs: adopt this span's real font/style.
            keep = {"text", "bbox", "origin", "parts", "primary_text"}
            merged.update({k: v for k, v in span.items() if k not in keep})
            merged["primary_tagged"] = False
    return merged


def line_runs(line: dict, tagged: set[str]) -> list[dict]:
    direction = tuple(line.get("dir", (1.0, 0.0)))
    runs: list[dict] = []
    for span in line.get("spans", []):
        if not span.get("text"):
            continue
        if runs and _joinable(runs[-1], span, tagged, direction):
            runs[-1] = _extend_run(runs[-1], span, tagged)
        else:
            runs.append(_start_run(span, tagged))
    return [run for run in runs if run["text"].strip()]


def page_text_model(page: fitz.Page) -> dict:
    tagged = tagged_font_names(page)
    blocks = []
    for b_index, block in enumerate(page_dict(page).get("blocks", [])):
        if block.get("type", 0) != 0:
            continue
        lines = []
        for l_index, line in enumerate(block.get("lines", [])):
            direction = tuple(line.get("dir", (1.0, 0.0)))
            spans = [
                _span_model(page, run, f"{b_index}-{l_index}-{r_index}", direction)
                for r_index, run in enumerate(line_runs(line, tagged))
            ]
            if spans:
                lines.append({
                    "id": f"{b_index}-{l_index}",
                    "bbox": to_display_rect(page, line["bbox"]),
                    "dir": to_display_vector(page, direction),
                    "spans": spans,
                })
        if lines:
            blocks.append({"id": str(b_index), "bbox": to_display_rect(page, block["bbox"]), "lines": lines})
    words = [
        {"bbox": to_display_rect(page, w[:4]), "text": w[4], "block": w[5], "line": w[6], "word": w[7]}
        for w in page.get_text("words", flags=TEXT_FLAGS, sort=False)
    ]
    return {"blocks": blocks, "words": words}


def find_span(page: fitz.Page, bbox: tuple, origin: tuple | None, text: str) -> tuple[dict, list[dict], int] | None:
    """Locate the run matching a display-space snapshot.

    Returns (line, runs_of_line, index) in unrotated page space.
    """
    target = fitz.Rect(bbox) * page.derotation_matrix
    target.normalize()
    target_origin = fitz.Point(origin) * page.derotation_matrix if origin else None
    tagged = tagged_font_names(page)
    best: tuple[float, tuple[dict, list[dict], int]] | None = None
    for block in page_dict(page).get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            runs = line_runs(line, tagged)
            for index, run in enumerate(runs):
                score = _match_score(run, target, target_origin, text)
                if score is not None and (best is None or score < best[0]):
                    best = (score, (line, runs, index))
    return best[1] if best else None


def _match_score(span: dict, target: fitz.Rect, origin: fitz.Point | None, text: str) -> float | None:
    rect = fitz.Rect(span["bbox"])
    if not (rect + (-3, -3, 3, 3)).intersects(target):
        return None
    score = abs(rect.x0 - target.x0) + abs(rect.y0 - target.y0) + abs(rect.x1 - target.x1) + abs(rect.y1 - target.y1)
    if origin is not None:
        span_origin = fitz.Point(span["origin"])
        score += abs(span_origin - origin)
    if span["text"] != text:
        score += 50 if text.strip() and span["text"].strip() == text.strip() else 500
    return score if score < 600 else None


def find_block(page: fitz.Page, bbox: tuple) -> dict | None:
    target = fitz.Rect(bbox) * page.derotation_matrix
    target.normalize()
    best: tuple[float, dict] | None = None
    for block in page_dict(page).get("blocks", []):
        if block.get("type", 0) != 0 or not block.get("lines"):
            continue
        rect = fitz.Rect(block["bbox"])
        if not rect.intersects(target):
            continue
        overlap = abs(rect & target)
        union = abs(rect | target) or 1.0
        score = 1.0 - overlap / union
        if best is None or score < best[0]:
            best = (score, block)
    return best[1] if best and best[0] < 0.5 else None
