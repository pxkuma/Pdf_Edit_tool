"""Changing comments: adding notes and markup, editing, replying, setting a review status, deleting."""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf as fitz

from . import annotmeta, annots
from .annots import AnnotStyle
from .comments import (
    COMMENT_SUBTYPES,
    MODEL_MARKED,
    MODEL_REVIEW,
    REVIEW_STATES,
    CommentError,
    collect,
)

RECORD_FLAGS = 28  # print + no zoom + no rotate, like the replies Acrobat writes
SUBJECTS = {
    "note": "Sticky Note", "highlight": "Highlight", "underline": "Underline", "strikeout": "Strikeout",
    "squiggly": "Squiggly", "textbox": "Text Box",
}
DEFAULT_COLORS = {"note": "#ffd400", "highlight": "#ffd400", "underline": "#16a34a", "strikeout": "#dc2626",
                  "squiggly": "#dc2626", "textbox": "#2563eb"}
COMMENT_KINDS = tuple(SUBJECTS)
STATUSES = tuple(state.lower() for state in REVIEW_STATES)
MAX_TEXT = 20000


@dataclass(frozen=True)
class NewComment:
    """A comment to create. Coordinates are display (rotated page, y-down) points."""

    kind: str
    text: str = ""
    author: str = ""
    subject: str = ""
    color: str | None = None
    point: tuple[float, float] | None = None  # notes
    rects: tuple[tuple[float, float, float, float], ...] = ()  # highlight, underline, strikeout, squiggly
    rect: tuple[float, float, float, float] | None = None  # text boxes
    font_size: float = 12.0
    text_color: str = "#111111"
    icon: str = "Comment"


def _on_page(page: fitz.Page, xref: int) -> fitz.Annot | None:
    """The annotation ``xref`` of ``page``, or ``None`` (MuPDF raises for an xref that is not one)."""
    if not any(known[0] == xref for known in page.annot_xrefs()):
        return None
    return page.load_annot(xref)


def _load(page: fitz.Page, xref: int) -> fitz.Annot:
    annot = _on_page(page, xref)
    if annot is None or annot.type[1] not in COMMENT_SUBTYPES:
        raise CommentError("Comment not found (it may have been removed).")
    return annot


def _is_state(annot: fitz.Annot) -> bool:
    return annot.parent.parent.xref_get_key(annot.xref, "State")[0] != "null"


def _load_commentable(page: fitz.Page, xref: int) -> fitz.Annot:
    annot = _load(page, xref)
    if _is_state(annot):
        raise CommentError("A review state cannot be commented on.")
    return annot


def _clean(text: str, label: str, required: bool = False) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if required and not text.strip():
        raise CommentError(f"The {label} is empty.")
    if len(text) > MAX_TEXT:
        raise CommentError(f"The {label} is longer than {MAX_TEXT} characters.")
    return text


def add_comment(page: fitz.Page, new: NewComment) -> int:
    """Create a note, a text markup or a text box with its comment; returns the annotation's xref."""
    if new.kind not in COMMENT_KINDS:
        raise CommentError(f"Unknown comment type {new.kind}.")
    text = _clean(new.text, "comment")
    style = AnnotStyle(color=new.color or DEFAULT_COLORS[new.kind], contents=text, author=new.author,
                       opacity=0.6 if new.kind == "highlight" else 1.0)
    if new.kind == "note":
        if new.point is None:
            raise CommentError("A note needs a position.")
        xref = annots.add_note(page, new.point, style, new.icon)
    elif new.kind == "textbox":
        if new.rect is None:
            raise CommentError("A text box needs an area.")
        xref = annots.add_textbox(page, new.rect, text, new.font_size, style, new.text_color)
    else:
        xref = annots.add_markup(page, new.kind, list(new.rects), style)
    page.load_annot(xref).set_info(subject=new.subject or SUBJECTS[new.kind])
    return xref


def edit_comment(page: fitz.Page, xref: int, text: str | None = None, subject: str | None = None) -> None:
    annot = _load_commentable(page, xref)
    if text is not None:
        annot.set_info(content=_clean(text, "comment"))
        if annot.type[1] == "FreeText":
            annot.update()  # a text box draws its text, so its appearance must follow
    if subject is not None:
        annot.set_info(subject=_clean(subject, "subject")[:200])
    annotmeta.touch(annot)


def add_record(page: fitz.Page, parent: fitz.Annot, text: str, author: str, state: tuple[str, str] | None) -> int:
    """A reply or a state: a hidden Text annotation that points at ``parent``."""
    doc = page.parent
    record = page.add_text_annot(parent.rect.tl, text, icon="Note")
    record.set_irt_xref(parent.xref)
    doc.xref_set_key(record.xref, "RT", "/R")
    if state:
        doc.xref_set_key(record.xref, "StateModel", fitz.get_pdf_str(state[0]))
        doc.xref_set_key(record.xref, "State", fitz.get_pdf_str(state[1]))
    record.set_flags(RECORD_FLAGS)
    annotmeta.blank_appearance(record)
    annotmeta.stamp_new(record, author)
    return record.xref


def add_reply(page: fitz.Page, parent_xref: int, text: str, author: str = "") -> int:
    parent = _load_commentable(page, parent_xref)
    return add_record(page, parent, _clean(text, "reply", required=True), author, None)


def set_status(page: fitz.Page, xref: int, status: str, author: str = "") -> int:
    """Record a review status (none, accepted, rejected, cancelled, completed) as Acrobat does."""
    if status not in STATUSES:
        raise CommentError(f"Unknown status {status}.")
    parent = _load_commentable(page, xref)
    state = REVIEW_STATES[STATUSES.index(status)]
    text = f"{state} set by {author or 'Unknown'}"
    return add_record(page, parent, text, author, (MODEL_REVIEW, state))


def set_checked(page: fitz.Page, xref: int, checked: bool, author: str = "") -> int:
    parent = _load_commentable(page, xref)
    state = "Marked" if checked else "Unmarked"
    return add_record(page, parent, f"{state} set by {author or 'Unknown'}", author, (MODEL_MARKED, state))


def delete_comment(page: fitz.Page, xref: int) -> int:
    """Delete a comment or a reply together with everything that hangs off it; returns how many."""
    _load(page, xref)
    entries = {e.xref: e for e in collect(page.parent, [page.number], {page.number: page})}
    target = entries.get(xref)
    if target is None:
        raise CommentError("Comment not found (it may have been removed).")
    doomed: list = []
    pending = [target]
    while pending:
        node = pending.pop()
        doomed.append(node)
        pending.extend(node.children)
    for node in reversed(doomed):  # the deepest first: MuPDF removes a deleted annotation's replies as well
        annot = _on_page(page, node.xref)
        if annot is not None:
            page.delete_annot(annot)
    return len(doomed)
