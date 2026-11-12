"""Compare two PDF documents and build the report.

The caller supplies the documents as functions (``source``), and a lock that guards every MuPDF call,
so a long comparison never holds the global lock for more than one page. Nothing here changes a
document.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

import pymupdf as fitz

from ..geometry import Rect4
from .align import PagePair, align_pages, signature
from .explain import explained_by_text
from .textdiff import TextChange, diff_words
from .visual import compare_pages
from .words import PageContent, image_rects, read_page

Mode = Literal["text", "visual", "both"]
MAX_VISUAL_PAIRS = 300  # pages that are rendered twice and compared pixel by pixel
SIZE_TOLERANCE = 0.5  # points
SNIPPET_WORDS = 12
OPTION_DEFAULT_DPI = 72


class CompareError(ValueError):
    """A comparison that cannot be done; the message is meant for the user."""


class Progress(Protocol):
    total: int

    def advance(self, message: str = "") -> None: ...


class _NoProgress:
    total = 0

    def advance(self, message: str = "") -> None:
        pass


@dataclass(frozen=True)
class CompareOptions:
    mode: Mode = "both"
    dpi: int = OPTION_DEFAULT_DPI
    sensitivity: str = "medium"
    ignore_case: bool = False

    @property
    def text(self) -> bool:
        return self.mode in ("text", "both")

    @property
    def visual(self) -> bool:
        return self.mode in ("visual", "both")

    def as_dict(self) -> dict:
        return {"mode": self.mode, "dpi": self.dpi, "sensitivity": self.sensitivity, "ignoreCase": self.ignore_case}


Source = Callable[[], fitz.Document]


def _rects(rects: tuple[Rect4, ...]) -> list[list[float]]:
    return [list(rect) for rect in rects]


def _text_change(change: TextChange) -> dict:
    return {
        "kind": "text", "type": change.type, "oldText": change.old_text, "newText": change.new_text,
        "before": change.before, "after": change.after,
        "rectsA": _rects(change.rects_a), "rectsB": _rects(change.rects_b),
        "anchorA": list(change.anchor_a) if change.anchor_a else None,
        "anchorB": list(change.anchor_b) if change.anchor_b else None,
    }


def _change(kind: str, type_: str, **fields) -> dict:
    return {"kind": kind, "type": type_, "oldText": "", "newText": "", "before": "", "after": "",
            "rectsA": [], "rectsB": [], "anchorA": None, "anchorB": None, **fields}


def _snippet(content: PageContent) -> str:
    return " ".join(word.text for word in content.words[:SNIPPET_WORDS])


def _size_text(size: tuple[float, float]) -> str:
    return f"{size[0]:g} x {size[1]:g} pt"


def _position(change: dict) -> tuple[float, float]:
    for key in ("rectsB", "rectsA"):
        if change[key]:
            return change[key][0][1], change[key][0][0]
    marker = change["anchorA"] or change["anchorB"]
    return (marker[1], marker[0]) if marker else (0.0, 0.0)


def _single_page(pair: PagePair, content: PageContent) -> dict:
    inserted = pair.a is None
    whole = [[0.0, 0.0, content.size[0], content.size[1]]]
    change = _change(
        "page", "insert" if inserted else "delete",
        newText=_snippet(content) if inserted else "", oldText="" if inserted else _snippet(content),
        rectsA=[] if inserted else whole, rectsB=whole if inserted else [],
    )
    words = len(content.words)
    return {
        "status": "inserted" if inserted else "removed", "similarity": 0.0,
        "sizeA": None if inserted else list(content.size), "sizeB": list(content.size) if inserted else None,
        "sizeChanged": False, "visual": None, "changes": [change],
        "text": {"wordsA": 0 if inserted else words, "wordsB": words if inserted else 0, "inserted": words if inserted else 0,
                 "deleted": 0 if inserted else words},
    }


def _visual_changes(regions, text_changes: list[dict], images: list[Rect4]) -> tuple[list[dict], int]:
    """The visual regions that no text change explains, and how many were left out as explained."""
    text_rects = [tuple(r) for c in text_changes for key in ("rectsA", "rectsB") for r in c[key]]
    text_rects += [tuple(c[key]) for c in text_changes for key in ("anchorA", "anchorB") if c[key]]
    kept, explained = [], 0
    for region in regions:
        if text_changes and explained_by_text(region.rect, text_rects, images):
            explained += 1
            continue
        rect = [list(region.rect)]
        kept.append(_change("visual", "region", rectsA=rect, rectsB=rect, pixels=region.pixels))
    return kept, explained


def _pair_report(pair: PagePair, a: PageContent, b: PageContent, sources: tuple[Source, Source],
                 options: CompareOptions, lock: AbstractContextManager) -> dict:
    changes: list[dict] = []
    text = None
    if options.text:
        found = diff_words(a.words, b.words)
        changes.extend(_text_change(c) for c in found)
        text = {"wordsA": len(a.words), "wordsB": len(b.words),
                "inserted": sum(c.words_inserted for c in found), "deleted": sum(c.words_deleted for c in found)}
    size_changed = abs(a.size[0] - b.size[0]) > SIZE_TOLERANCE or abs(a.size[1] - b.size[1]) > SIZE_TOLERANCE
    if size_changed:
        changes.append(_change("page", "resize", oldText=_size_text(a.size), newText=_size_text(b.size)))
    visual = None
    if options.visual:
        with lock:
            page_a, page_b = sources[0]()[pair.a], sources[1]()[pair.b]
            regions, dpi = compare_pages(page_a, page_b, options.dpi, options.sensitivity)
            images = image_rects(page_a) + image_rects(page_b) if regions else []
        found, explained = _visual_changes(regions, [c for c in changes if c["kind"] == "text"], images)
        changes.extend(found)
        visual = {"dpi": dpi, "regions": len(found), "explainedByText": explained}
    changes.sort(key=_position)
    return {
        "status": "changed" if changes else "matched", "similarity": pair.similarity,
        "sizeA": list(a.size), "sizeB": list(b.size), "sizeChanged": size_changed,
        "text": text, "visual": visual, "changes": changes,
    }


def _totals(pairs: list[dict]) -> dict:
    changes = [c for p in pairs for c in p["changes"]]

    def count(status: str) -> int:
        return sum(1 for p in pairs if p["status"] == status)

    texts = [p["text"] for p in pairs if p["text"]]
    return {
        "pairs": len(pairs), "matched": count("matched"), "changed": count("changed"),
        "inserted": count("inserted"), "removed": count("removed"),
        "changes": len(changes),
        "textChanges": sum(1 for c in changes if c["kind"] == "text"),
        "visualChanges": sum(1 for c in changes if c["kind"] == "visual"),
        "pageChanges": sum(1 for c in changes if c["kind"] == "page"),
        "pagesWithChanges": sum(1 for p in pairs if p["status"] != "matched"),
        "wordsInserted": sum(t["inserted"] for t in texts), "wordsDeleted": sum(t["deleted"] for t in texts),
    }


def _read_all(source: Source, count: int, options: CompareOptions, lock: AbstractContextManager, progress: Progress,
              label: str) -> list[PageContent]:
    contents = []
    for index in range(count):
        with lock:
            contents.append(read_page(source()[index], options.ignore_case))
        progress.advance(f"Reading {label} page {index + 1}")
    return contents


def compare_documents(source_a: Source, source_b: Source, options: CompareOptions,
                      lock: AbstractContextManager | None = None, progress: Progress | None = None) -> dict:
    """Compare the document of ``source_a`` (the original) with that of ``source_b`` (the revised one)."""
    lock = lock or nullcontext()
    progress = progress or _NoProgress()
    with lock:
        count_a, count_b = source_a().page_count, source_b().page_count
    progress.total = count_a + count_b
    contents_a = _read_all(source_a, count_a, options, lock, progress, "first document")
    contents_b = _read_all(source_b, count_b, options, lock, progress, "second document")
    pairs = align_pages([signature(c) for c in contents_a], [signature(c) for c in contents_b])
    if options.visual and sum(1 for p in pairs if p.a is not None and p.b is not None) > MAX_VISUAL_PAIRS:
        raise CompareError(f"A visual comparison covers at most {MAX_VISUAL_PAIRS} pages. Compare the text instead, or use smaller documents.")
    progress.total += len(pairs)
    report_pairs = []
    for index, pair in enumerate(pairs):
        if pair.a is not None and pair.b is not None:
            body = _pair_report(pair, contents_a[pair.a], contents_b[pair.b], (source_a, source_b), options, lock)
        else:
            body = _single_page(pair, contents_b[pair.b] if pair.a is None else contents_a[pair.a])
        report_pairs.append({"index": index, "pageA": pair.a, "pageB": pair.b, **body})
        progress.advance(f"Compared page pair {index + 1} of {len(pairs)}")
    serial = 0
    for pair in report_pairs:  # numbered in reading order across the whole document
        for change in pair["changes"]:
            change.update(id=f"c{serial}", pair=pair["index"], pageA=pair["pageA"], pageB=pair["pageB"])
            serial += 1
    return {"options": options.as_dict(), "pairs": report_pairs, "totals": _totals(report_pairs)}
