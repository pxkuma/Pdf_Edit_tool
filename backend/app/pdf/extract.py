"""Builds the page model consumed by the editor UI (all coordinates in display space)."""

from __future__ import annotations

import pymupdf as fitz

from . import pdfobj, textstate
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
    """Text dict with span text plus the origin of each span's first non-space glyph."""
    data = page.get_text("rawdict", flags=TEXT_FLAGS)
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                chars = span.pop("chars", [])
                span["text"] = "".join(ch["c"] for ch in chars)
                first = next((ch for ch in chars if not ch["c"].isspace()), None)
                span["first_origin"] = tuple(first["origin"]) if first else tuple(span["origin"])
                span["last_origin"] = tuple(chars[-1]["origin"]) if chars else tuple(span["origin"])
    return data


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
    if span.get("alpha", 255) == 0 or run.get("alpha", 255) == 0:
        return False  # invisible (OCR) words stay individually editable
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
              "parts": run["parts"] + [span], "last_origin": span.get("last_origin", span["origin"])}
    if not is_tagged:
        merged["primary_text"] = run["primary_text"] + span["text"]
        if run["primary_tagged"]:
            # The run began with fallback glyphs: adopt this span's real font/style.
            keep = {"text", "bbox", "origin", "parts", "primary_text", "last_origin"}
            merged.update({k: v for k, v in span.items() if k not in keep})
            merged["primary_tagged"] = False
    return merged


def _primary_part(run: dict, tagged: set[str]) -> dict:
    for part in run["parts"]:
        if normalize_font_name(part["font"]) not in tagged:
            return part
    return run["parts"][0]


def attach_records(doc: fitz.Document, runs: list[dict], direction: tuple, records: list, tagged: set[str]) -> list[dict]:
    """Attach the exact text state (textstate.TextRecord) behind each run, if found."""
    if not records:
        return runs
    result = []
    for run in runs:
        part = _primary_part(run, tagged)
        origin = tuple(part.get("first_origin", part["origin"]))
        record = textstate.match_record(records, origin, direction, part["font"], doc)
        result.append({**run, "record": record})
    return result


def exact_style(doc: fitz.Document, page: fitz.Page, run: dict) -> dict:
    """Exact style details for the UI (falls back to MuPDF's normalised values)."""
    record = run.get("record")
    if record is None:
        return {"hscale": 100.0, "charSpacing": None, "wordSpacing": 0.0, "rise": 0.0, "render": "fill",
                "renderMode": 0, "colorSpace": "RGB", "skew": 0.0, "ocr": False, "exact": False}
    return {
        "size": round(record.effective_size, 2),
        "hscale": round(record.effective_hscale, 2),
        "charSpacing": round(record.page_char_spacing, 3),
        "wordSpacing": round(record.page_word_spacing, 3),
        "rise": round(record.page_rise, 3),
        "render": textstate.RENDER_MODES.get(record.render_mode, "fill"),
        "renderMode": record.render_mode,
        "colorSpace": textstate.describe_paint(doc, page, record.stroke if record.render_mode in (1, 5) else record.fill),
        "skew": round(record.skew, 3),
        "opacity": round(textstate.fill_opacity(doc, page, record), 3),
        "ocr": record.render_mode in (3, 7),
        "exact": True,
    }


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
    doc = page.parent
    records = textstate.page_text_records(doc, page)
    blocks = []
    for b_index, block in enumerate(page_dict(page).get("blocks", [])):
        if block.get("type", 0) != 0:
            continue
        lines = []
        for l_index, line in enumerate(block.get("lines", [])):
            direction = tuple(line.get("dir", (1.0, 0.0)))
            runs = attach_records(doc, line_runs(line, tagged), direction, records, tagged)
            spans = [
                {**_span_model(page, run, f"{b_index}-{l_index}-{r_index}", direction), **exact_style(doc, page, run)}
                for r_index, run in enumerate(runs)
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
    records = textstate.page_text_records(page.parent, page)
    best: tuple[float, tuple[dict, list[dict], int]] | None = None
    for block in page_dict(page).get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            runs = attach_records(page.parent, line_runs(line, tagged), tuple(line.get("dir", (1.0, 0.0))), records, tagged)
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


def find_box_lines(page: fitz.Page, bbox: tuple) -> tuple[dict, list[dict]] | None:
    """The block containing a text box and the lines of it inside the box.

    A text box may cover only part of a block: MuPDF often groups a label and its
    value (or the cells of a table row) on one baseline into a single block.
    """
    target = fitz.Rect(bbox) * page.derotation_matrix
    target.normalize()
    area = abs(target) or 1.0
    grown = target + (-1.5, -1.5, 1.5, 1.5)
    best: tuple[float, dict, list[dict]] | None = None
    for block in page_dict(page).get("blocks", []):
        if block.get("type", 0) != 0 or not block.get("lines"):
            continue
        covered = abs(fitz.Rect(block["bbox"]) & target) / area
        if covered < 0.5 or (best is not None and covered <= best[0]):
            continue
        lines = []
        for line in block["lines"]:
            rect = fitz.Rect(line["bbox"])
            centre = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
            if centre in grown:
                lines.append(line)
        if lines:
            best = (covered, block, lines)
    return (best[1], best[2]) if best else None
