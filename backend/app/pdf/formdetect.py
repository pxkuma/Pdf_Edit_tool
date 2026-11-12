"""Field recognition: propose form fields from what a page looks like (Acrobat's "auto-detect form fields").

Heuristics, tuned for precision over recall: a proposal needs a strong visual cue *and* (except for runs of
underscores) a label next to it.

* text fields: horizontal rules ("Name: ______" drawn as a line), runs of underscores typed as text, and
  empty rectangles with a label to the left or above. A rule with text sitting on it is an underline, not a
  field; long rules without a label are separators.
* checkboxes: small empty squares (drawn or the ☐ glyph) with a label beside them.
* labels mentioning a signature give a signature field; labels mentioning a date give a date-formatted field.

Nothing is written to the document: the result is a list of proposals the user accepts or rejects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf as fitz

from .formnames import DEFAULT_BASES, field_index, unique_variant
from .geometry import to_display_rect

MIN_LINE = 36.0  # shortest rule that can be a field, in points
MAX_RULE = 1.6  # thickest "line" (thin filled rectangles count as rules)
BOX_SIZES = (6.0, 24.0)  # checkbox side
LABEL_GAP = 90.0  # farthest a label can be from its field
FIELD_HEIGHT = (12.0, 22.0)
MIN_CONFIDENCE = 0.6
CHECK_GLYPHS = set("☐□❏❑▢◻⬜")
_UNDERSCORES = re.compile(r"_{4,}")
_SIGNATURE = re.compile(r"\bsign(ature|ed|\s+here)?\b", re.IGNORECASE)
_DATE = re.compile(r"\bdate\b|\bdob\b", re.IGNORECASE)


@dataclass(frozen=True)
class Word:
    rect: fitz.Rect
    text: str
    line: tuple[int, int]  # (block, line) from MuPDF


@dataclass(frozen=True)
class Proposal:
    kind: str
    rect: fitz.Rect  # unrotated page space
    label: str
    confidence: float
    reason: str
    multiline: bool = False
    date: bool = False


# ------------------------------------------------------------------ primitives
def _words(page: fitz.Page) -> list[Word]:
    return [Word(fitz.Rect(w[:4]), w[4], (w[5], w[6])) for w in page.get_text("words") if w[4].strip()]


def _shapes(page: fitz.Page) -> tuple[list[tuple[float, float, float]], list[fitz.Rect]]:
    """Horizontal rules (x0, x1, y) and rectangles drawn on the page."""
    rules, boxes = [], []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.y - b.y) < 0.8 and abs(a.x - b.x) >= MIN_LINE:
                    rules.append((min(a.x, b.x), max(a.x, b.x), (a.y + b.y) / 2))
            elif item[0] in ("re", "qu"):
                rect = fitz.Rect(item[1].rect if item[0] == "qu" else item[1])
                if rect.height <= MAX_RULE and rect.width >= MIN_LINE:
                    rules.append((rect.x0, rect.x1, (rect.y0 + rect.y1) / 2))
                elif rect.width >= BOX_SIZES[0] and rect.height >= BOX_SIZES[0]:
                    boxes.append(rect)
    return rules, boxes


def _overlap(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = fitz.Rect(a) & b
    if inter.is_empty:
        return 0.0
    return inter.get_area() / max(1e-6, min(a.get_area(), b.get_area()))


def _clean_label(text: str) -> str:
    text = _UNDERSCORES.sub(" ", text)
    text = re.sub(r"[\s:*_.]+$", "", " ".join(text.split()))
    return text.strip(" :*")[:60]


# ------------------------------------------------------------------ labels
def _line_text(words: list[Word], line: tuple[int, int], before_x: float) -> str:
    parts = [w for w in words if w.line == line and w.rect.x1 <= before_x + 1]
    return " ".join(w.text for w in sorted(parts, key=lambda w: w.rect.x0)[-6:])


def _label_left(words: list[Word], rect: fitz.Rect) -> tuple[str, bool]:
    """Text ending just left of ``rect`` on the same line; the flag says whether it ends with a colon."""
    centre = (rect.y0 + rect.y1) / 2
    near = [w for w in words if w.rect.x1 <= rect.x0 + 2 and rect.x0 - w.rect.x1 <= LABEL_GAP
            and w.rect.y0 - 3 <= centre <= w.rect.y1 + 3]
    if not near:
        return "", False
    last = max(near, key=lambda w: w.rect.x1)
    text = _line_text(words, last.line, last.rect.x1)
    return _clean_label(text), text.rstrip().endswith(":")


def _label_right(words: list[Word], rect: fitz.Rect) -> str:
    centre = (rect.y0 + rect.y1) / 2
    near = [w for w in words if w.rect.x0 >= rect.x1 - 1 and w.rect.x0 - rect.x1 <= 30
            and w.rect.y0 - 2 <= centre <= w.rect.y1 + 2]
    if not near:
        return ""
    first = min(near, key=lambda w: w.rect.x0)
    parts = sorted((w for w in words if w.line == first.line and w.rect.x0 >= first.rect.x0), key=lambda w: w.rect.x0)
    return _clean_label(" ".join(w.text for w in parts[:6]))


def _label_above(words: list[Word], rect: fitz.Rect) -> str:
    near = [w for w in words if 0 <= rect.y0 - w.rect.y1 <= 14 and w.rect.x0 >= rect.x0 - 4 and w.rect.x0 <= rect.x0 + 40]
    if not near:
        return ""
    first = min(near, key=lambda w: w.rect.x0)
    return _clean_label(_line_text(words, first.line, rect.x1))


def _label_below(words: list[Word], x0: float, x1: float, y: float) -> str:
    near = [w for w in words if 0.5 <= w.rect.y0 - y <= 12 and w.rect.x0 >= x0 - 4 and w.rect.x1 <= x1 + 4]
    if not near:
        return ""
    first = min(near, key=lambda w: w.rect.x0)
    return _clean_label(_line_text(words, first.line, x1))


# ------------------------------------------------------------------ candidates
def _field_height(words: list[Word], rect_hint: fitz.Rect) -> float:
    sizes = [w.rect.height for w in words if abs((w.rect.y0 + w.rect.y1) / 2 - rect_hint.y1) < 20]
    size = sorted(sizes)[len(sizes) // 2] if sizes else 14.0
    return max(FIELD_HEIGHT[0], min(FIELD_HEIGHT[1], size * 1.25))


def _from_rule(words: list[Word], x0: float, x1: float, y: float, page_width: float) -> Proposal | None:
    probe = fitz.Rect(x0, y - 16, x1, y)
    height = _field_height(words, probe)
    rect = fitz.Rect(x0, y - height, x1, y - 0.5)
    for word in words:  # text written on the rule: an underline or a filled-in value, not an empty field
        if _overlap(word.rect, rect) > 0.3 and word.rect.width > 2 and not _UNDERSCORES.fullmatch(word.text):
            return None
    label, colon = _label_left(words, rect)
    reason = "label and line"
    if not label:
        label, colon = _label_below(words, x0, x1, y), False
        reason = "line with caption below"
    if not label or (x1 - x0 > page_width * 0.8 and not colon):
        return None
    return Proposal("text", rect, label, 0.8 if colon else 0.65, reason)


def _from_underscores(words: list[Word]) -> list[Proposal]:
    found = []
    for word in words:
        match = _UNDERSCORES.search(word.text)
        if not match:
            continue
        share = word.rect.width / max(1, len(word.text))
        x0, x1 = word.rect.x0 + match.start() * share, word.rect.x0 + match.end() * share
        if x1 - x0 < 20:
            continue
        height = max(FIELD_HEIGHT[0], min(FIELD_HEIGHT[1], word.rect.height * 1.2))
        rect = fitz.Rect(x0, word.rect.y1 - height, x1, word.rect.y1 - word.rect.height * 0.15)
        prefix = _clean_label(word.text[: match.start()])
        label = prefix or _label_left(words, rect)[0] or _label_below(words, x0, x1, word.rect.y1)
        found.append(Proposal("text", rect, label, 0.8 if label else 0.6, "underscores"))
    return found


def _empty(words: list[Word], rect: fitz.Rect) -> bool:
    return not any(_overlap(w.rect, rect) > 0.2 for w in words)


def _from_box(words: list[Word], box: fitz.Rect, boxes: list[fitz.Rect]) -> Proposal | None:
    if not _empty(words, box):
        return None
    side_lo, side_hi = BOX_SIZES
    square = abs(box.width - box.height) <= 0.2 * max(box.width, box.height)
    if square and side_lo <= box.width <= side_hi:
        label = _label_right(words, box) or _label_left(words, box)[0]
        return Proposal("checkbox", box, label, 0.85, "square with label") if label else None
    if box.width < MIN_LINE or box.height < FIELD_HEIGHT[0] - 2 or box.height > 300:
        return None
    if any(other != box and box.contains(other) for other in boxes):
        return None  # a frame around other boxes (a table or a panel)
    label = _label_left(words, box)[0] or _label_above(words, box)
    if not label:
        return None
    return Proposal("text", box, label, 0.75, "empty box with label", multiline=box.height > 36)


def _from_glyphs(words: list[Word]) -> list[Proposal]:
    found = []
    for word in words:
        if word.text in CHECK_GLYPHS:
            side = min(word.rect.width, word.rect.height)
            rect = fitz.Rect(word.rect.x0, word.rect.y1 - side, word.rect.x0 + side, word.rect.y1)
            label = _label_right(words, word.rect)
            if label:
                found.append(Proposal("checkbox", rect, label, 0.8, "box character with label"))
    return found


def _refine(proposal: Proposal) -> Proposal:
    if proposal.kind != "text":
        return proposal
    if _SIGNATURE.search(proposal.label):
        return Proposal("signature", proposal.rect, proposal.label, proposal.confidence, proposal.reason)
    if _DATE.search(proposal.label) and not proposal.multiline:
        return Proposal("text", proposal.rect, proposal.label, proposal.confidence, proposal.reason, date=True)
    return proposal


def _dedupe(proposals: list[Proposal], taken: list[fitz.Rect]) -> list[Proposal]:
    kept: list[Proposal] = []
    for proposal in sorted(proposals, key=lambda p: -p.confidence):
        if proposal.confidence < MIN_CONFIDENCE:
            continue
        if any(_overlap(proposal.rect, other) > 0.3 for other in taken):
            continue
        if any(_overlap(proposal.rect, other.rect) > 0.3 for other in kept):
            continue
        kept.append(proposal)
    return sorted(kept, key=lambda p: (round(p.rect.y0), p.rect.x0))


def _name(proposal: Proposal, taken: set[str]) -> str:
    base = re.sub(r"[.\x00-\x1f]", "", proposal.label).strip()[:40] or DEFAULT_BASES[proposal.kind]
    name = unique_variant(taken, base)
    taken.add(name)
    return name


def detect_fields(doc: fitz.Document, page: fitz.Page) -> list[dict]:
    words = _words(page)
    rules, boxes = _shapes(page)
    candidates = [_from_rule(words, x0, x1, y, page.rect.width) for x0, x1, y in rules]
    candidates += [_from_box(words, box, boxes) for box in boxes]
    candidates += _from_underscores(words) + _from_glyphs(words)
    existing = [fitz.Rect(w.rect) for w in page.widgets() or []]
    proposals = _dedupe([_refine(c) for c in candidates if c is not None], existing)
    taken = set(field_index(doc))
    result = []
    for number, proposal in enumerate(proposals):
        result.append({
            "id": f"p{page.number}-{number}",
            "page": page.number,
            "kind": proposal.kind,
            "rect": to_display_rect(page, proposal.rect),
            "name": _name(proposal, taken),
            "label": proposal.label,
            "confidence": round(proposal.confidence, 2),
            "reason": proposal.reason,
            "multiline": proposal.multiline,
            "format": {"kind": "date", "pattern": "mm/dd/yyyy"} if proposal.date else None,
        })
    return result
