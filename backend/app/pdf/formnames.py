"""Field naming rules.

* A name is 1-120 characters after trimming, without periods (they separate levels of a hierarchical name)
  or control characters.
* A name identifies exactly one field. A new field cannot take a name that is already used, with one
  exception: a radio button may take the name of an existing radio group, which adds it to that group
  (each button of a group needs its own export value).
* Renaming to a name that is used by another field is refused. Renaming a radio button renames its group.
* Fields created without a name get Acrobat-style defaults: Text1, Check Box1, Radio Group1, Dropdown1...
"""

from __future__ import annotations

import re

import pymupdf as fitz

from . import formobj
from .formerror import FormError

MAX_NAME = 120
_FORBIDDEN = re.compile(r"[.\x00-\x1f\x7f]")
DEFAULT_BASES = {
    "text": "Text",
    "checkbox": "Check Box",
    "radio": "Radio Group",
    "combobox": "Dropdown",
    "listbox": "List Box",
    "button": "Button",
    "signature": "Signature",
}
_KINDS = {
    fitz.PDF_WIDGET_TYPE_TEXT: "text",
    fitz.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    fitz.PDF_WIDGET_TYPE_COMBOBOX: "combobox",
    fitz.PDF_WIDGET_TYPE_LISTBOX: "listbox",
    fitz.PDF_WIDGET_TYPE_SIGNATURE: "signature",
    fitz.PDF_WIDGET_TYPE_BUTTON: "button",
}


def clean_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        raise FormError("A field needs a name.")
    if len(text) > MAX_NAME:
        raise FormError(f"Field names can be at most {MAX_NAME} characters long.")
    if _FORBIDDEN.search(text):
        raise FormError("Field names cannot contain periods or control characters.")
    return text


def field_index(doc: fitz.Document) -> dict[str, tuple[str, int]]:
    """Fully qualified name -> (kind, field head xref) for every field with a widget."""
    index: dict[str, tuple[str, int]] = {}
    if not doc.is_pdf:
        return index
    for page in doc:
        for widget in page.widgets() or []:
            name = widget.field_name or ""
            if name and name not in index:
                index[name] = (_KINDS.get(widget.field_type, "unknown"), formobj.field_head(doc, widget.xref))
    return index


def _blocked_by_hierarchy(index: dict[str, tuple[str, int]], name: str) -> bool:
    """``name`` is a non-terminal node of a hierarchical name (``a`` when ``a.b`` exists)."""
    prefix = name + "."
    return any(existing.startswith(prefix) for existing in index)


def resolve_new_name(index: dict[str, tuple[str, int]], name: str, kind: str) -> int | None:
    """Validate the name of a new field. Returns the radio group head to join, or None for a new field."""
    if name in index:
        other_kind, head = index[name]
        if kind == "radio" and other_kind == "radio":
            return head
        raise FormError(f"A field named “{name}” already exists. Each field needs a unique name.")
    if _blocked_by_hierarchy(index, name):
        raise FormError(f"“{name}” is already used as the parent of other fields.")
    return None


def auto_name(taken, kind: str, base: str | None = None) -> str:
    stem = base or DEFAULT_BASES.get(kind, "Field")
    number = 1
    while f"{stem}{number}" in taken or any(t.startswith(f"{stem}{number}.") for t in taken):
        number += 1
    return f"{stem}{number}"


def unique_variant(taken, name: str) -> str:
    """``name``, or ``name_2``, ``name_3``... when it is taken (used when accepting detected fields)."""
    if name not in taken:
        return name
    number = 2
    while f"{name}_{number}" in taken:
        number += 1
    return f"{name}_{number}"


def _qualified(doc: fitz.Document, head: int, name: str) -> str:
    parts = [name]
    current = formobj.parent_of(doc, head)
    for _ in range(32):
        if current is None:
            break
        kind, value = doc.xref_get_key(current, "T")
        if kind == "string":
            parts.insert(0, value)
        current = formobj.parent_of(doc, current)
    return ".".join(parts)


def check_rename(doc: fitz.Document, head: int, name: str) -> str:
    """Validate renaming the field ``head`` to ``name`` (its last name part). Returns the clean name."""
    name = clean_name(name)
    full = _qualified(doc, head, name)
    index = field_index(doc)
    owner = index.get(full)
    if owner is not None and owner[1] != head:
        raise FormError(f"A field named “{full}” already exists. Each field needs a unique name.")
    if _blocked_by_hierarchy(index, full):
        raise FormError(f"“{full}” is already used as the parent of other fields.")
    return name
