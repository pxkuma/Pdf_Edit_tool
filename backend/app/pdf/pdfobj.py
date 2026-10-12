"""Small helpers for reading/writing raw PDF objects through PyMuPDF."""

from __future__ import annotations

import re

import pymupdf as fitz

_NUMBER = re.compile(r"-?\d*\.?\d+")
_REF = re.compile(r"^(\d+)\s+0\s+R$")


def ref_xref(value: str) -> int | None:
    match = _REF.match(value.strip())
    return int(match.group(1)) if match else None


def get_key(doc: fitz.Document, xref: int, key: str) -> tuple[str, str]:
    try:
        return doc.xref_get_key(xref, key)
    except Exception:  # noqa: BLE001 - PyMuPDF raises generic errors
        return ("null", "null")


def resolve(doc: fitz.Document, xref: int, key: str) -> tuple[str, str, int | None]:
    """Return (type, value, xref_of_value). Indirect values are dereferenced."""
    kind, value = get_key(doc, xref, key)
    if kind == "xref":
        target = ref_xref(value)
        if target is None:
            return ("null", "null", None)
        return ("object", doc.xref_object(target, compressed=True), target)
    return (kind, value, None)


def read_number_array(doc: fitz.Document, xref: int, key: str) -> list[float]:
    kind, value, _ = resolve(doc, xref, key)
    if kind in ("null", "dict"):
        return []
    return [float(n) for n in _NUMBER.findall(_strip_refs(value))]


def _strip_refs(text: str) -> str:
    return re.sub(r"\d+\s+0\s+R", " ", text)


def read_name(doc: fitz.Document, xref: int, key: str) -> str:
    kind, value = get_key(doc, xref, key)
    if kind == "name":
        return value.lstrip("/")
    return ""


def first_array_ref(doc: fitz.Document, xref: int, key: str) -> int | None:
    kind, value = get_key(doc, xref, key)
    if kind == "xref":
        inner = ref_xref(value)
        if inner is None:
            return None
        value = doc.xref_object(inner, compressed=True)
    match = re.search(r"(\d+)\s+0\s+R", value)
    return int(match.group(1)) if match else None


def stream_text(doc: fitz.Document, xref: int) -> str:
    try:
        raw = doc.xref_stream(xref)
    except Exception:  # noqa: BLE001
        return ""
    return raw.decode("latin-1") if raw else ""


def append_content(doc: fitz.Document, page: fitz.Page, content: bytes) -> int:
    """Append a new content stream to the page (drawn on top of existing content)."""
    if not page.is_wrapped:
        page.wrap_contents()
    new_xref = doc.get_new_xref()
    doc.update_object(new_xref, "<<>>")
    doc.update_stream(new_xref, content)
    kind, value = get_key(doc, page.xref, "Contents")
    if kind == "array":
        existing = value.strip()[1:-1]
    elif kind == "xref":
        target = ref_xref(value)
        existing = value
        if target is not None and doc.xref_object(target).lstrip().startswith("["):
            existing = doc.xref_object(target).strip()[1:-1]
    else:
        existing = ""
    doc.xref_set_key(page.xref, "Contents", f"[{existing} {new_xref} 0 R]")
    return new_xref


def _resources_target(doc: fitz.Document, page: fitz.Page) -> tuple[int, str]:
    """Return (xref, path_prefix) where the page resource dictionary lives."""
    kind, value = get_key(doc, page.xref, "Resources")
    if kind == "xref":
        target = ref_xref(value)
        if target is not None:
            return target, ""
    if kind == "dict":
        return page.xref, "Resources/"
    inherited = _inherited_resources(doc, page.xref)
    doc.xref_set_key(page.xref, "Resources", inherited or "<<>>")
    return _resources_target(doc, page)


def _inherited_resources(doc: fitz.Document, xref: int) -> str | None:
    seen: set[int] = set()
    parent = ref_xref(get_key(doc, xref, "Parent")[1])
    while parent is not None and parent not in seen:
        seen.add(parent)
        kind, value = get_key(doc, parent, "Resources")
        if kind in ("xref", "dict"):
            return value
        parent = ref_xref(get_key(doc, parent, "Parent")[1])
    return None


def add_resource(doc: fitz.Document, page: fitz.Page, category: str, name: str, value: str) -> None:
    """Register ``value`` under /Resources/<category>/<name> for this page."""
    target, prefix = _resources_target(doc, page)
    kind, cat_value = get_key(doc, target, f"{prefix}{category}")
    if kind == "xref":
        cat_xref = ref_xref(cat_value)
        if cat_xref is not None:
            doc.xref_set_key(cat_xref, name, value)
            return
    doc.xref_set_key(target, f"{prefix}{category}/{name}", value)


def resource_exists(doc: fitz.Document, page: fitz.Page, category: str, name: str) -> str | None:
    target, prefix = _resources_target(doc, page)
    kind, cat_value = get_key(doc, target, f"{prefix}{category}")
    if kind == "xref":
        cat_xref = ref_xref(cat_value)
        if cat_xref is None:
            return None
        kind, value = get_key(doc, cat_xref, name)
    else:
        kind, value = get_key(doc, target, f"{prefix}{category}/{name}")
    return None if kind == "null" else value
