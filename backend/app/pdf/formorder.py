"""Tab order of the form fields on a page.

Viewers move between fields in the order of the page's /Annots array unless the page's /Tabs entry asks for
row (/R) or column (/C) order. PDF Studio always writes the explicit order into /Annots, so every viewer
follows it, and sets /Tabs to say how it was made:

* ``manual``: the user's order; /Tabs is removed so viewers use the array order;
* ``row`` / ``column``: fields sorted by position; /Tabs /R or /C is written as well.
"""

from __future__ import annotations

import pymupdf as fitz

from . import formobj
from .formerror import FormError
from .geometry import to_display_rect
from .pdfobj import get_key

MODES = {"/R": "row", "/C": "column", "/S": "structure"}


def _widgets(page: fitz.Page) -> list[fitz.Widget]:
    return list(page.widgets() or [])


def tab_mode(doc: fitz.Document, page: fitz.Page) -> str:
    kind, value = get_key(doc, page.xref, "Tabs")
    return MODES.get(value, "manual") if kind == "name" else "manual"


def tab_order(doc: fitz.Document, page: fitz.Page) -> dict:
    fields = [
        {"xref": w.xref, "name": w.field_name or "", "rect": to_display_rect(page, w.rect)}
        for w in _widgets(page)
    ]
    return {"page": page.number, "mode": tab_mode(doc, page), "fields": fields}


def _same_line(a: tuple, b: tuple, axis: int) -> bool:
    """Two display rects share a row (axis 1) or a column (axis 0) when their centre bands overlap."""
    lo, hi = (1, 3) if axis == 1 else (0, 2)
    size = min(a[hi] - a[lo], b[hi] - b[lo])
    centre_a, centre_b = (a[lo] + a[hi]) / 2, (b[lo] + b[hi]) / 2
    return abs(centre_a - centre_b) <= max(2.0, size / 2)


def sorted_order(items: list[tuple[int, tuple]], mode: str) -> list[int]:
    """Field xrefs sorted into rows (top to bottom, left to right) or columns (left to right, top to bottom)."""
    across, along = (1, 0) if mode == "row" else (0, 1)
    remaining = sorted(items, key=lambda item: (item[1][across], item[1][along]))
    lines: list[list[tuple[int, tuple]]] = []
    for item in remaining:
        if lines and _same_line(lines[-1][0][1], item[1], across):
            lines[-1].append(item)
        else:
            lines.append([item])
    return [xref for line in lines for xref, _rect in sorted(line, key=lambda item: item[1][along])]


def set_tab_order(doc: fitz.Document, page: fitz.Page, order: list[int] | None, mode: str) -> list[int]:
    widgets = _widgets(page)
    present = [w.xref for w in widgets]
    if mode in ("row", "column"):
        order = sorted_order([(w.xref, to_display_rect(page, w.rect)) for w in widgets], mode)
    elif mode != "manual":
        raise FormError("Unknown tab order.")
    if order is None or sorted(order) != sorted(present):
        raise FormError("The tab order must list every field of the page exactly once.")
    annots, holder = formobj.array_refs(doc, page.xref, "Annots")
    queue = iter(order)
    wanted = set(order)
    rebuilt = [next(queue) if ref in wanted else ref for ref in annots]
    formobj.write_array(doc, page.xref, "Annots", rebuilt, holder)
    if mode == "manual":
        formobj.del_key(doc, page.xref, "Tabs")
    else:
        doc.xref_set_key(page.xref, "Tabs", "/R" if mode == "row" else "/C")
    return order
