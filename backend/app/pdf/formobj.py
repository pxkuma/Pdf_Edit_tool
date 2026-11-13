"""Raw AcroForm object plumbing: field heads, radio-group hierarchy, the /Fields array and AcroForm defaults.

A *widget* is the annotation on the page. A *field* is the dictionary that carries the name (/T) and the
value (/V). For a simple field both are the same object; a radio group is one parent field whose /Kids are
the buttons. Everything here works on raw objects through PyMuPDF's xref API, so it also understands
forms made by other tools.
"""

from __future__ import annotations

import re

import pymupdf as fitz
from pymupdf import mupdf

from .pdfobj import get_key, ref_xref

_REFS = re.compile(r"(\d+)\s+0\s+R")
_NAME_SAFE = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.*+,;:!?@'~^`|=&$")

# Standard 14 fonts every viewer has; /DA strings refer to them by these resource names.
STANDARD_FONTS = {
    "Helv": "Helvetica",
    "HeBo": "Helvetica-Bold",
    "TiRo": "Times-Roman",
    "TiBo": "Times-Bold",
    "Cour": "Courier",
    "CoBo": "Courier-Bold",
    "ZaDb": "ZapfDingbats",
}


def pdf_name(value: str) -> str:
    """``value`` as a PDF name token (with the slash), escaping anything outside the regular characters."""
    out = []
    for byte in value.encode("utf-8"):
        out.append(chr(byte) if byte in _NAME_SAFE else f"#{byte:02X}")
    return "/" + "".join(out)


def del_key(doc: fitz.Document, xref: int, path: str) -> None:
    """Really remove a key (``MK/BG`` style paths allowed); a ``null`` value would still block inheritance."""
    obj = mupdf.pdf_load_object(mupdf.pdf_document_from_fz_document(doc.this), xref)
    *parents, last = path.split("/")
    for part in parents:
        obj = mupdf.pdf_dict_gets(obj, part)
        if not mupdf.pdf_is_dict(obj):
            return
    mupdf.pdf_dict_dels(obj, last)


def decode_name(token: str) -> str:
    """A raw name token (without the slash) with its #XX escapes decoded."""
    raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), token.encode("latin-1", errors="replace"))
    return raw.decode("utf-8", errors="replace")


def pdf_strings(array_text: str) -> list[str]:
    """The literal strings of a raw array, e.g. ``[(a)(b\\)c)]``."""
    return [re.sub(r"\\(.)", r"\1", item) for item in re.findall(r"\(((?:[^()\\]|\\.)*)\)", array_text)]


def refs(text: str) -> list[int]:
    return [int(n) for n in _REFS.findall(text)]


def array_refs(doc: fitz.Document, xref: int, key: str) -> tuple[list[int], int | None]:
    """References in the array ``key`` of ``xref`` and, when the array is an indirect object, its xref."""
    kind, value = get_key(doc, xref, key)
    if kind == "xref":
        target = ref_xref(value)
        if target is None:
            return [], None
        return refs(doc.xref_object(target, compressed=True)), target
    if kind == "array":
        return refs(value), None
    return [], None


def write_array(doc: fitz.Document, xref: int, key: str, items: list[int], holder: int | None) -> None:
    text = "[" + " ".join(f"{item} 0 R" for item in items) + "]"
    if holder is not None:
        doc.update_object(holder, text)
    else:
        doc.xref_set_key(xref, key, text)


def parent_of(doc: fitz.Document, xref: int) -> int | None:
    kind, value = get_key(doc, xref, "Parent")
    return ref_xref(value) if kind == "xref" else None


def has_own_name(doc: fitz.Document, xref: int) -> bool:
    return get_key(doc, xref, "T")[0] == "string"


def field_head(doc: fitz.Document, xref: int) -> int:
    """The object that holds the field's name and value (the widget itself or its nearest named parent)."""
    current = xref
    for _ in range(32):  # guard against cyclic /Parent chains
        if has_own_name(doc, current):
            return current
        parent = parent_of(doc, current)
        if parent is None:
            return current
        current = parent
    return xref


def kids_of(doc: fitz.Document, xref: int) -> list[int]:
    return array_refs(doc, xref, "Kids")[0]


def acroform_xref(doc: fitz.Document) -> int:
    """The AcroForm dictionary as an indirect object (created or moved out of the catalog when needed)."""
    catalog = doc.pdf_catalog()
    kind, value = get_key(doc, catalog, "AcroForm")
    if kind == "xref":
        target = ref_xref(value)
        if target is not None:
            return target
    xref = doc.get_new_xref()
    doc.update_object(xref, value if kind == "dict" else "<</Fields[]>>")
    doc.xref_set_key(catalog, "AcroForm", f"{xref} 0 R")
    return xref


def replace_in_container(doc: fitz.Document, child: int, replacement: int | None) -> None:
    """Swap (or remove, when ``replacement`` is None) ``child`` in its parent's /Kids or in AcroForm/Fields."""
    parent = parent_of(doc, child)
    holder_xref, key = (parent, "Kids") if parent is not None else (acroform_xref(doc), "Fields")
    items, holder = array_refs(doc, holder_xref, key)
    if child not in items:
        if replacement is not None and parent is None:
            items.append(replacement)
            write_array(doc, holder_xref, key, items, holder)
        return
    updated = [replacement if item == child else item for item in items if replacement is not None or item != child]
    write_array(doc, holder_xref, key, updated, holder)


def ensure_defaults(doc: fitz.Document) -> None:
    """Give the AcroForm what other viewers need to regenerate appearances: /DR fonts, /DA, no NeedAppearances."""
    form = acroform_xref(doc)
    for name, base in STANDARD_FONTS.items():
        if get_key(doc, form, f"DR/Font/{name}")[0] == "null":
            encoding = "" if name == "ZaDb" else "/Encoding/WinAnsiEncoding"
            doc.xref_set_key(form, f"DR/Font/{name}", f"<</Type/Font/Subtype/Type1/BaseFont/{base}{encoding}>>")
    if get_key(doc, form, "DA")[0] == "null":
        doc.xref_set_key(form, "DA", fitz.get_pdf_str("/Helv 0 Tf 0 g"))
    if get_key(doc, form, "NeedAppearances")[0] != "null":
        doc.xref_set_key(form, "NeedAppearances", "false")


def fix_sig_flags(doc: fitz.Document, any_signed: bool) -> None:
    """SignaturesExist only, unless a signature is actually present (AppendOnly would mislead viewers)."""
    form = acroform_xref(doc)
    doc.xref_set_key(form, "SigFlags", "3" if any_signed else "1")


def to_radio_group(doc: fitz.Document, widget_xref: int) -> int:
    """Make sure the radio widget is a kid of a parent field; return the parent (the group's field)."""
    if not has_own_name(doc, widget_xref):
        return field_head(doc, widget_xref)
    if kids_of(doc, widget_xref):
        return widget_xref  # already a group field
    group = doc.get_new_xref()
    doc.update_object(group, "<<>>")
    for key in ("T", "TU", "FT", "Ff", "V", "DV", "TM"):
        kind, value = get_key(doc, widget_xref, key)
        if kind != "null":
            doc.xref_set_key(group, key, fitz.get_pdf_str(value) if kind == "string" else value)
    if get_key(doc, group, "V")[0] == "null":
        doc.xref_set_key(group, "V", "/Off")
    container = parent_of(doc, widget_xref)
    replace_in_container(doc, widget_xref, group)
    if container is not None:
        doc.xref_set_key(group, "Parent", f"{container} 0 R")
    doc.xref_set_key(group, "Kids", f"[{widget_xref} 0 R]")
    for key in ("T", "TU", "FT", "Ff", "V", "DV", "TM"):
        del_key(doc, widget_xref, key)
    doc.xref_set_key(widget_xref, "Parent", f"{group} 0 R")
    return group


def add_kid(doc: fitz.Document, group: int, widget_xref: int) -> None:
    """Move a freshly created radio widget (a top-level field) into ``group``."""
    replace_in_container(doc, widget_xref, None)
    kids, holder = array_refs(doc, group, "Kids")
    write_array(doc, group, "Kids", [*kids, widget_xref], holder)
    for key in ("T", "TU", "FT", "Ff", "V", "DV", "TM"):
        del_key(doc, widget_xref, key)
    doc.xref_set_key(widget_xref, "Parent", f"{group} 0 R")


def on_state_names(doc: fitz.Document, widget_xref: int) -> list[str]:
    """Raw (still escaped) names of the non-Off appearance states."""
    kind, value = get_key(doc, widget_xref, "AP/N")
    if kind == "xref":
        target = ref_xref(value)
        value = doc.xref_object(target, compressed=True) if target else ""
    elif kind != "dict":
        return []
    return [name for name in re.findall(r"/([^\s/<>\[\]()]+)\s+\d+\s+0\s+R", value) if name != "Off"]


def rename_on_state(doc: fitz.Document, widget_xref: int, new_name: str) -> None:
    """Rename the 'on' appearance state of a checkbox/radio widget (its export value), in /N and /D."""
    token = pdf_name(new_name)
    for path in ("AP/N", "AP/D"):
        kind, value = get_key(doc, widget_xref, path)
        if kind != "dict":
            continue
        entries = re.findall(r"/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R", value)
        rebuilt = "".join(f"/Off {ref} 0 R" if name == "Off" else f"{token} {ref} 0 R" for name, ref in entries)
        doc.xref_set_key(widget_xref, path, f"<<{rebuilt}>>")
    if get_key(doc, widget_xref, "AS")[0] == "name" and get_key(doc, widget_xref, "AS")[1] != "/Off":
        doc.xref_set_key(widget_xref, "AS", token)


def set_name_value(doc: fitz.Document, head: int, state: str) -> None:
    """Buttons store their value as a name (/Yes), not a string; MuPDF writes a string, so fix it up."""
    doc.xref_set_key(head, "V", "/Off" if state in ("", "Off") else pdf_name(state))
