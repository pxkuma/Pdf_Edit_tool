"""Merge the comments of an XFDF file into a document, the way Acrobat's Import Comments does.

* A comment whose name (``name`` in XFDF, ``/NM`` in the PDF) matches one already on that page of the
  same kind is *updated*; every other comment is *added*, so importing a file twice changes nothing
  the second time.
* A reply is attached to the comment named by ``inreplyto``, whether that comment comes from the
  same file or is already in the document. Replies are imported after the comments they answer.
  A reply to a comment that cannot be found becomes a comment of its own; a review state without
  its comment is skipped.
* Everything else that cannot be imported is skipped and reported, never guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf as fitz

from . import annotmeta
from .annots import keep_rect
from .commentops import MAX_TEXT, add_record
from .comments import MODEL_MARKED, MODEL_REVIEW, REVIEW_STATES, Entry, collect
from .geometry import color_to_hex, hex_to_rgb
from .pdfdates import format_pdf_date, now_pdf, parse_pdf_date
from .xfdf_export import FLAG_NAMES, LINE_ENDS, TAGS
from .xfdf_parse import XfdfAnnotation, XfdfError, numbers, pairs, read_xfdf
from .xfdf_space import PageSpace

SUBTYPES = {tag: subtype for subtype, tag in TAGS.items()}
MARKUP_ADDERS = {"highlight": "add_highlight_annot", "underline": "add_underline_annot",
                 "strikeout": "add_strikeout_annot", "squiggly": "add_squiggly_annot"}
STATES = {MODEL_REVIEW: REVIEW_STATES, MODEL_MARKED: ("Marked", "Unmarked")}
ICONS = {"Comment", "Key", "Note", "Help", "NewParagraph", "Paragraph", "Insert"}
FLAG_BITS = {name: bit for bit, name in FLAG_NAMES}
BOXED = {"square", "circle"}
SHAPE_TYPES = {"ink", "line", "square", "circle", "polygon", "polyline"}
MAX_WARNINGS = 25
MAX_SHORT = 200

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")
_DA_SIZE = re.compile(r"([\d.]+)\s+Tf")
_DA_RGB = re.compile(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg")
_DA_GRAY = re.compile(r"([\d.]+)\s+g\b")


@dataclass
class ImportReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)

    def warn(self, message: str) -> None:
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)

    def skip(self, item: XfdfAnnotation, reason: str) -> None:
        self.skipped += 1
        self.warn(f"Skipped {item.label()}: {reason}")

    def as_dict(self) -> dict:
        return {"added": self.added, "updated": self.updated, "unchanged": self.unchanged,
                "skipped": self.skipped, "warnings": self.warnings, "pages": sorted(self.pages)}


# ------------------------------------------------------------------ attribute readers
def _text(item: XfdfAnnotation, key: str, limit: int = MAX_SHORT) -> str:
    return item.attrs.get(key, "")[:limit]


def _color(value: str | None) -> tuple[float, float, float] | None:
    return hex_to_rgb(value) if value and _HEX.match(value.strip()) else None


def _flags(value: str | None) -> int | None:
    if not value or not value.strip():
        return None
    total = 0
    for part in value.replace(";", ",").split(","):
        part = part.strip().lower()
        if part.isdigit():
            total |= int(part)
        elif part in FLAG_BITS:
            total |= FLAG_BITS[part]
    return total & 0xFFF


def _pdf_date(value: str | None) -> str | None:
    moment = parse_pdf_date(value)
    return format_pdf_date(moment) if moment else None


def _float(value: str | None, low: float, high: float) -> float | None:
    try:
        number = float(value) if value is not None else None
    except ValueError:
        return None
    return None if number is None or not low <= number <= high else number


def _rect(item: XfdfAnnotation) -> tuple[float, float, float, float] | None:
    if "rect" not in item.attrs:
        return None
    values = numbers(item.attrs["rect"], "rect", 4)
    if len(values) != 4:
        raise XfdfError("the rectangle needs four numbers")
    return (values[0], values[1], values[2], values[3])


def _point(item: XfdfAnnotation, key: str) -> tuple[float, float]:
    values = numbers(item.attrs.get(key, ""), key, 2)
    if len(values) != 2:
        raise XfdfError(f"{key} needs an x and a y value")
    return (values[0], values[1])


# ------------------------------------------------------------------ creating annotations
def _need_rect(item: XfdfAnnotation, space: PageSpace) -> fitz.Rect:
    rect = _rect(item)
    if rect is None:
        raise XfdfError("it has no rectangle")
    return space.rect(rect)


def _make_text(page: fitz.Page, space: PageSpace, item: XfdfAnnotation) -> fitz.Annot:
    rect = _need_rect(item, space)
    icon = item.attrs.get("icon", "Note")
    return page.add_text_annot(rect.tl, item.contents[:MAX_TEXT], icon=icon if icon in ICONS else "Note")


def _make_caret(page: fitz.Page, space: PageSpace, item: XfdfAnnotation) -> fitz.Annot:
    return page.add_caret_annot(_need_rect(item, space).tl)


def _make_markup(page: fitz.Page, space: PageSpace, item: XfdfAnnotation) -> fitz.Annot:
    if "coords" in item.attrs:
        corners = [space.point(p) for p in pairs(numbers(item.attrs["coords"], "coords"), "coords")]
        if not corners or len(corners) % 4:
            raise XfdfError("coords must hold four points per highlighted line")
        quads = [fitz.Quad(*corners[i:i + 4]) for i in range(0, len(corners), 4)]
    else:
        quads = [_need_rect(item, space).quad]
    return getattr(page, MARKUP_ADDERS[item.tag])(quads=quads)


def _appearance(default_appearance: str) -> tuple[float, tuple[float, ...]]:
    """Font size and text color out of a default appearance string such as ``0 0 1 rg /Helv 12 Tf``."""
    size, rgb, gray = (r.search(default_appearance) for r in (_DA_SIZE, _DA_RGB, _DA_GRAY))
    color = tuple(float(v) for v in rgb.groups()) if rgb else ((float(gray.group(1)),) * 3 if gray else (0.0, 0.0, 0.0))
    return max(4.0, min(144.0, float(size.group(1)) if size else 12.0)), color


def _make_free_text(page: fitz.Page, space: PageSpace, item: XfdfAnnotation) -> fitz.Annot:
    rect = _need_rect(item, space)
    size, text_color = _appearance(item.default_appearance)
    width = _float(item.attrs.get("width"), 0, 50)
    width = 1.0 if width is None else width
    inner = fitz.Rect(rect.x0 + width / 2, rect.y0 + width / 2, rect.x1 - width / 2, rect.y1 - width / 2)
    return page.add_freetext_annot(  # MuPDF grows the box by half the border on each side
        rect if inner.is_empty else inner, item.contents[:MAX_TEXT], fontsize=size, fontname="helv",
        text_color=text_color, fill_color=_color(item.attrs.get("color")), border_width=width, rotate=page.rotation,
    )


def _make_ink(page: fitz.Page, space: PageSpace, item: XfdfAnnotation) -> fitz.Annot:
    strokes = [[tuple(space.point(p)) for p in stroke] for stroke in item.ink if len(stroke) >= 2]
    if not strokes:
        raise XfdfError("it has no drawing")
    return page.add_ink_annot(strokes)


def _make_line(page: fitz.Page, space: PageSpace, item: XfdfAnnotation) -> fitz.Annot:
    annot = page.add_line_annot(space.point(_point(item, "start")), space.point(_point(item, "end")))
    ends = [LINE_ENDS.index(item.attrs[key]) if item.attrs.get(key) in LINE_ENDS else 0 for key in ("head", "tail")]
    annot.set_line_ends(*ends)
    return annot


def _make_shape(page: fitz.Page, space: PageSpace, item: XfdfAnnotation) -> fitz.Annot:
    rect = _need_rect(item, space)
    return page.add_rect_annot(rect) if item.tag == "square" else page.add_circle_annot(rect)


def _make_poly(page: fitz.Page, space: PageSpace, item: XfdfAnnotation) -> fitz.Annot:
    needed = 3 if item.tag == "polygon" else 2
    if len(item.vertices) < needed:
        raise XfdfError(f"it needs at least {needed} vertices")
    points = [space.point(p) for p in item.vertices]
    return page.add_polygon_annot(points) if item.tag == "polygon" else page.add_polyline_annot(points)


BUILDERS = {
    "text": _make_text, "caret": _make_caret, "freetext": _make_free_text, "ink": _make_ink, "line": _make_line,
    "square": _make_shape, "circle": _make_shape, "polygon": _make_poly, "polyline": _make_poly,
    **dict.fromkeys(MARKUP_ADDERS, _make_markup),
}


# ------------------------------------------------------------------ properties shared by every kind
def _style(annot: fitz.Annot, item: XfdfAnnotation) -> None:
    colors = {}
    stroke, fill = _color(item.attrs.get("color")), _color(item.attrs.get("interior-color"))
    if stroke and item.tag != "freetext":
        colors["stroke"] = stroke
    if fill and item.tag in SHAPE_TYPES:
        colors["fill"] = fill
    if colors:
        annot.set_colors(**colors)
    opacity = _float(item.attrs.get("opacity"), 0, 1)
    if opacity is not None:
        annot.set_opacity(max(0.05, opacity))
    width = _float(item.attrs.get("width"), 0, 50)
    if width is not None and item.tag in SHAPE_TYPES:
        annot.set_border(width=width)


def _style_differs(annot: fitz.Annot, item: XfdfAnnotation) -> bool:
    colors, stroke = annot.colors or {}, _color(item.attrs.get("color"))
    if stroke and item.tag != "freetext" and color_to_hex(colors.get("stroke")) != color_to_hex(stroke):
        return True
    opacity = _float(item.attrs.get("opacity"), 0, 1)
    return opacity is not None and abs(opacity - (annot.opacity if annot.opacity >= 0 else 1.0)) > 0.01


def _identify(annot: fitz.Annot, item: XfdfAnnotation, name: str, comment: str | None = None) -> None:
    """Author, subject, text, dates, flags and name."""
    stamp = now_pdf()
    annotmeta.set_name(annot, name)
    modified = _pdf_date(item.attrs.get("date")) or stamp
    annot.set_info(
        title=_text(item, "title"), subject=_text(item, "subject"),
        content=item.contents[:MAX_TEXT] if comment is None else comment,
        creationDate=_pdf_date(item.attrs.get("creationdate")) or modified, modDate=modified,
    )
    flags = _flags(item.attrs.get("flags"))
    if flags is not None:
        annot.set_flags(flags)


# ------------------------------------------------------------------ the merge
class Merge:
    def __init__(self, doc: fitz.Document) -> None:
        self.doc = doc
        self.sheets: dict[int, fitz.Page] = {}
        self.spaces: dict[int, PageSpace] = {}
        entries = collect(doc, sheets=self.sheets)
        self.existing: dict[tuple[int, str], Entry] = {(e.page, e.name): e for e in entries}
        self.used = set(self.existing)
        self.resolved: dict[tuple[int, str], int] = {key: e.xref for key, e in self.existing.items()}
        self.report = ImportReport()

    def run(self, items: tuple[XfdfAnnotation, ...]) -> ImportReport:
        replies = []
        for item in items:
            if item.tag == "popup":
                continue  # the pop-up window of a comment: not a comment
            if item.tag not in BUILDERS:
                self.report.skip(item, f"{item.tag} annotations are not supported")
            elif item.attrs.get("inreplyto"):
                replies.append(item)
            else:
                self._import(item)
        self._import_replies(replies)
        return self.report

    def _import_replies(self, pending: list[XfdfAnnotation]) -> None:
        while pending:
            ready = [r for r in pending if self._parent_key(r) in self.resolved]
            if not ready:
                break
            for item in ready:
                self._import(item)
            pending = [r for r in pending if r not in ready]
        for item in pending:  # the comment they answer is nowhere to be found
            if item.attrs.get("state"):
                self.report.skip(item, "the comment it sets a state on does not exist")
            else:
                self.report.warn(f"{item.label()} answers a comment that is not in the document; imported as a comment.")
                self._import(item, orphan=True)

    def _parent_key(self, item: XfdfAnnotation) -> tuple[int, str]:
        return (self._page_number(item), item.attrs["inreplyto"])

    def _page_number(self, item: XfdfAnnotation) -> int:
        try:
            index = int(item.attrs.get("page", ""))
        except ValueError as exc:
            raise XfdfError("it has no page number") from exc
        if not 0 <= index < self.doc.page_count:
            raise XfdfError(f"page {index} does not exist (the document has {self.doc.page_count})")
        return index

    def _import(self, item: XfdfAnnotation, orphan: bool = False) -> None:
        try:
            index = self._page_number(item)
            if index not in self.sheets:
                self.sheets[index] = self.doc[index]
            page = self.sheets[index]
            space = self.spaces.setdefault(index, PageSpace(page))
            name = _text(item, "name")
            match = self.existing.get((index, name)) if name else None
            if match is not None and match.subtype == SUBTYPES[item.tag]:
                changed = self._update(match, item)
            else:
                self._add(page, space, item, name, orphan)
                changed = True
            if changed:
                self.report.pages.add(index)
        except (XfdfError, ValueError, RuntimeError, TypeError) as exc:
            self.report.skip(item, str(exc))

    def _unique(self, index: int, name: str) -> str:
        if name and (index, name) not in self.used:
            return name
        fresh = annotmeta.new_name()
        if name:
            self.report.warn(f"The name {name!r} is already used on page {index + 1}; the comment got a new one.")
        return fresh

    def _add(self, page: fitz.Page, space: PageSpace, item: XfdfAnnotation, name: str, orphan: bool) -> None:
        index = page.number
        name = self._unique(index, name)
        parent_xref = None if orphan else self.resolved.get((index, item.attrs.get("inreplyto", "")))
        if item.attrs.get("state") and parent_xref is None:
            raise XfdfError("a review state needs the comment it belongs to")
        annot = self._record(page, parent_xref, item) if parent_xref else BUILDERS[item.tag](page, space, item)
        try:
            if not parent_xref:
                _style(annot, item)
                annot.update()
                if item.tag in BOXED:
                    keep_rect(annot, _need_rect(item, space))  # a border must not make the box grow
            _identify(annot, item, name)
        except Exception:
            page.delete_annot(annot)  # never leave a half-made comment behind
            raise
        self.used.add((index, name))
        self.resolved[(index, name)] = annot.xref
        self.report.added += 1

    def _record(self, page: fitz.Page, parent_xref: int, item: XfdfAnnotation) -> fitz.Annot:
        parent = page.load_annot(parent_xref)
        if parent is None:
            raise XfdfError("the comment it answers is gone")
        state = self._state(item)
        record = page.load_annot(add_record(page, parent, item.contents[:MAX_TEXT], _text(item, "title"), state))
        if item.attrs.get("replytype", "").lower() == "group":
            page.parent.xref_set_key(record.xref, "RT", "/Group")
        return record

    @staticmethod
    def _state(item: XfdfAnnotation) -> tuple[str, str] | None:
        state = item.attrs.get("state")
        if not state:
            return None
        model = item.attrs.get("statemodel") or (MODEL_MARKED if state in STATES[MODEL_MARKED] else MODEL_REVIEW)
        allowed = STATES.get(model)
        value = state.title() if model == MODEL_REVIEW else state
        if allowed is None or value not in allowed:
            raise XfdfError(f"unknown state {state!r} for model {model!r}")
        return (model, value)

    def _update(self, entry: Entry, item: XfdfAnnotation) -> bool:
        """Bring a comment that is already in the document up to date; whether anything changed."""
        annot = entry.annot
        before = (entry.info.get("content", ""), entry.info.get("title", ""), entry.info.get("subject", ""))
        after = (item.contents[:MAX_TEXT], _text(item, "title"), _text(item, "subject"))
        restyle = entry.role == "comment" and _style_differs(annot, item)
        if before == after and not restyle:
            self.report.unchanged += 1
            return False
        annot.set_info(content=after[0], title=after[1], subject=after[2],
                       modDate=_pdf_date(item.attrs.get("date")) or now_pdf())
        if restyle:
            _style(annot, item)
        if restyle or (entry.role == "comment" and entry.subtype == "FreeText"):
            annot.update()  # redraw the appearance with the new colors or text
        self.report.updated += 1
        return True


def import_xfdf(doc: fitz.Document, data: bytes) -> ImportReport:
    """Read ``data`` (an XFDF file) and merge its comments into ``doc``."""
    return Merge(doc).run(read_xfdf(data).annotations)
