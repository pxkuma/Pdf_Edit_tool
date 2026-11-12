"""The comment model: PDF annotations seen the way Acrobat's Comments list sees them.

* A *comment* is a markup annotation (note, highlight, underline, strikeout, squiggly, text box,
  drawing, shape ...). Its text is ``/Contents``, its author ``/T`` and its dates ``/CreationDate``
  and ``/M``.
* A *reply* is a hidden Text annotation pointing at the comment it answers with ``/IRT`` (and
  ``/RT /R``). Replies can answer replies, which gives a thread.
* A *state* is another hidden Text annotation pointing at a comment with ``/IRT`` that carries
  ``/StateModel`` and ``/State``: ``Review`` (None, Accepted, Rejected, Cancelled, Completed) or
  ``Marked`` (Marked, Unmarked). The latest state of each model is the comment's status.

Reading is here, writing is in ``commentops``; both XFDF modules build on ``collect``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

import pymupdf as fitz

from . import annotmeta
from .annots import AnnotationError
from .geometry import color_to_hex, to_display_rect
from .pdfdates import to_iso

COMMENT_SUBTYPES = frozenset({
    "Text", "Highlight", "Underline", "StrikeOut", "Squiggly", "FreeText", "Ink", "Line", "Square",
    "Circle", "Polygon", "PolyLine", "Caret", "Stamp",
})
MARKUP_SUBTYPES = frozenset({"Highlight", "Underline", "StrikeOut", "Squiggly"})
REVIEW_STATES = ("None", "Accepted", "Rejected", "Cancelled", "Completed")
MODEL_REVIEW, MODEL_MARKED = "Review", "Marked"
MAX_QUOTE = 300
MAX_THREAD_DEPTH = 50


class CommentError(AnnotationError):
    pass


@dataclass
class Entry:
    """One comment-related annotation of the document and its place in a thread."""

    page: int
    sheet: fitz.Page  # kept so that ``annot`` stays valid: an annotation only holds a weak reference to its page
    xref: int
    annot: fitz.Annot
    subtype: str
    parent_xref: int  # 0: not a reply
    state: str  # "Accepted", "Marked" ...; empty unless this annotation records a state
    state_model: str
    name: str = ""  # unique name (see ``effective_names``)
    parent: "Entry | None" = None
    children: list["Entry"] = field(default_factory=list)

    @property
    def role(self) -> str:
        if self.state:
            return "state"
        return "reply" if self.parent is not None else "comment"

    @property
    def info(self) -> dict:
        return self.annot.info or {}

    @property
    def sort_key(self) -> tuple:
        info = self.info
        return (to_iso(info.get("creationDate")) or to_iso(info.get("modDate")), self.xref)


def _key(doc: fitz.Document, xref: int, key: str) -> str:
    kind, value = doc.xref_get_key(xref, key)
    return value if kind in ("string", "name") else ""


def collect(doc: fitz.Document, pages: Iterable[int] | None = None, sheets: dict[int, fitz.Page] | None = None) -> list[Entry]:
    """Every comment, reply and state of the document (or of ``pages``), linked into threads, in page order.

    ``sheets`` holds page objects already in use; further pages are loaded into it. Changes must go
    through the same page object that was read, because each load of a page keeps its own annotation list.
    """
    entries: list[Entry] = []
    sheets = {} if sheets is None else sheets
    for index in range(doc.page_count) if pages is None else pages:
        if index not in sheets:
            sheets[index] = doc[index]
        sheet = sheets[index]
        page_entries = []
        for annot in sheet.annots() or []:
            subtype = annot.type[1]
            if subtype not in COMMENT_SUBTYPES:
                continue
            xref = annot.xref
            page_entries.append(Entry(index, sheet, xref, annot, subtype, annot.irt_xref,
                                      _key(doc, xref, "State"), _key(doc, xref, "StateModel")))
        _link(page_entries)
        entries.extend(page_entries)
    effective_names(entries)
    return entries


def _link(entries: list[Entry]) -> None:
    """Attach each reply to its comment. A reply whose target is gone, loops back, or sits deeper than
    ``MAX_THREAD_DEPTH`` stays a comment of its own, so a damaged or hostile file cannot make a thread endless."""
    by_xref = {e.xref: e for e in entries}
    for entry in entries:
        parent = by_xref.get(entry.parent_xref) if entry.parent_xref else None
        if parent is None or parent is entry:
            continue
        ancestors = _ancestors(parent)
        if entry in ancestors or len(ancestors) >= MAX_THREAD_DEPTH:
            continue
        entry.parent = parent
        parent.children.append(entry)
    for entry in entries:
        entry.children.sort(key=lambda e: e.sort_key)


def _ancestors(entry: Entry) -> list[Entry]:
    """``entry`` and everything above it (links made so far form chains no longer than the cap)."""
    chain = []
    node: Entry | None = entry
    while node is not None:
        chain.append(node)
        node = node.parent
    return chain


def effective_names(entries: list[Entry]) -> None:
    """Name every entry: its own ``/NM`` when that identifies it, else a stable fingerprint.

    The fingerprint (page, type, place, author, date, parent) lets comments of older files, which have
    no usable names, be matched again when their XFDF export is imported into the same document.
    """
    taken: dict[str, int] = {}

    def name_of(entry: Entry, visiting: frozenset[int] = frozenset()) -> str:
        if entry.name:
            return entry.name
        own = annotmeta.name_of(entry.annot)
        if annotmeta.is_identity(own):
            entry.name = own
        else:
            parent_name = ""
            if entry.parent is not None and entry.xref not in visiting:
                parent_name = name_of(entry.parent, visiting | {entry.xref})
            entry.name = _fingerprint(entry, parent_name)
        return entry.name

    for entry in entries:
        name = name_of(entry)
        count = taken.get(name, 0)
        taken[name] = count + 1
        if count:
            entry.name = f"{name}-{count + 1}"


def _fingerprint(entry: Entry, parent_name: str) -> str:
    info = entry.info
    rect = tuple(round(v) for v in entry.annot.rect)
    parts = (entry.page, entry.subtype, rect, info.get("title", ""), info.get("creationDate", ""),
             parent_name, entry.state, entry.state_model)
    digest = hashlib.sha1(repr(parts).encode("utf-8")).hexdigest()[:20]
    return f"pdfstudio-{digest}"


def _latest(states: list[Entry]) -> Entry | None:
    return max(states, key=lambda e: e.sort_key, default=None)


def review_status(entry: Entry) -> tuple[str, Entry | None]:
    """``(status, the state that set it)``; status is lower case, ``"none"`` when never reviewed."""
    latest = _latest([c for c in entry.children if c.role == "state" and c.state_model != MODEL_MARKED])
    return ((latest.state.lower() if latest and latest.state.title() in REVIEW_STATES else "none"), latest)


def is_checked(entry: Entry) -> bool:
    latest = _latest([c for c in entry.children if c.role == "state" and c.state_model == MODEL_MARKED])
    return bool(latest and latest.state == "Marked")


def _quote(page: fitz.Page, annot: fitz.Annot, textpage: fitz.TextPage | None) -> str:
    points = annot.vertices or []
    parts = []
    for i in range(0, len(points) - 3, 4):
        rect = fitz.Quad(points[i], points[i + 1], points[i + 2], points[i + 3]).rect
        parts.append(page.get_textbox(rect, textpage=textpage))
    return " ".join(" ".join(parts).split())[:MAX_QUOTE]


def _color(annot: fitz.Annot) -> str | None:
    colors = annot.colors or {}
    value = colors.get("stroke") or colors.get("fill")
    return color_to_hex(value) if value else None


def describe(entry: Entry, textpage: fitz.TextPage | None = None) -> dict:
    """The API form of a comment or reply (without its replies)."""
    page, info = entry.sheet, entry.info
    status, setter = review_status(entry)
    modified = to_iso(info.get("modDate"))
    created = to_iso(info.get("creationDate")) or modified
    data = {
        "id": f"{entry.page}:{entry.xref}",
        "page": entry.page,
        "xref": entry.xref,
        "name": entry.name,
        "type": entry.subtype,
        "author": info.get("title", ""),
        "subject": info.get("subject", ""),
        "contents": info.get("content", ""),
        "created": created,
        "modified": modified or created,
        "color": _color(entry.annot),
        "rect": to_display_rect(page, entry.annot.rect),
        "quote": _quote(page, entry.annot, textpage) if entry.subtype in MARKUP_SUBTYPES else "",
        "status": status,
        "statusBy": setter.info.get("title", "") if setter else "",
        "statusDate": to_iso(setter.info.get("modDate")) if setter else "",
        "checked": is_checked(entry),
        "parent": entry.parent.xref if entry.parent else None,
    }
    return data


def _descendants(entry: Entry, depth: int = 1) -> list[tuple[Entry, int]]:
    result = []
    for child in entry.children:
        if child.role == "reply":
            result.append((child, depth))
            result.extend(_descendants(child, depth + 1))
    return result


def list_comments(doc: fitz.Document) -> dict:
    """All comments with their reply threads, plus the authors that appear."""
    entries = collect(doc)
    textpages: dict[int, fitz.TextPage] = {}
    comments, authors, total = [], set(), 0

    def describe_on_page(entry: Entry) -> dict:
        if entry.subtype in MARKUP_SUBTYPES and entry.page not in textpages:
            textpages[entry.page] = entry.sheet.get_textpage()
        return describe(entry, textpages.get(entry.page))

    for entry in entries:
        if entry.role != "comment":
            continue
        data = describe_on_page(entry)
        data["replies"] = [{**describe_on_page(reply), "depth": depth} for reply, depth in _descendants(entry)]
        total += 1 + len(data["replies"])
        authors.update(a for a in [data["author"], *(r["author"] for r in data["replies"])] if a)
        comments.append(data)
    comments.sort(key=lambda c: (c["page"], c["rect"][1], c["rect"][0], c["xref"]))
    return {"comments": comments, "authors": sorted(authors, key=str.casefold), "count": total}
