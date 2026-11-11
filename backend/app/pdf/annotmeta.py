"""Identity and timestamps of annotations: the name (``/NM``), creation date and modification date.

Comments are matched across documents by name when XFDF is imported, so every annotation this app
creates gets a globally unique name. MuPDF's own ``fitz-A<n>`` names are only unique inside one
document, so they do not count as identities.
"""

from __future__ import annotations

import re
import uuid

import pymupdf as fitz

from .pdfdates import now_pdf

_WEAK_NAME = re.compile(r"^fitz-A\d+$")
_BLANK_FORM = "<< /Type /XObject /Subtype /Form /BBox [0 0 16 16] /Resources << >> >>"


def new_name() -> str:
    return str(uuid.uuid4())


def is_identity(name: str) -> bool:
    """Whether ``name`` identifies the annotation beyond this one document."""
    return bool(name) and not _WEAK_NAME.match(name)


def _doc(annot: fitz.Annot) -> fitz.Document:
    return annot.parent.parent


def name_of(annot: fitz.Annot) -> str:
    return (annot.info or {}).get("id", "")


def set_name(annot: fitz.Annot, name: str) -> None:
    _doc(annot).xref_set_key(annot.xref, "NM", fitz.get_pdf_str(name))


def stamp_new(annot: fitz.Annot, author: str = "", subject: str = "", when: str | None = None) -> None:
    """Give a freshly created annotation a unique name and its creation/modification dates."""
    stamp = when or now_pdf()
    if not is_identity(name_of(annot)):
        set_name(annot, new_name())
    info = {"creationDate": stamp, "modDate": stamp}
    if author:
        info["title"] = author
    if subject:
        info["subject"] = subject
    annot.set_info(**info)


def touch(annot: fitz.Annot, when: str | None = None) -> None:
    annot.set_info(modDate=when or now_pdf())


def blank_appearance(annot: fitz.Annot) -> None:
    """Give an annotation an empty appearance so that no viewer draws it.

    Replies and review states are listed in the thread of the comment they belong to: viewers show
    them as part of that comment, never as icons of their own.
    """
    doc = _doc(annot)
    form = doc.get_new_xref()
    doc.update_object(form, _BLANK_FORM)
    doc.update_stream(form, b" ")
    doc.xref_set_key(annot.xref, "AP", f"<< /N {form} 0 R >>")


def copy_identity(source: fitz.Annot, target: fitz.Annot) -> None:
    """Carry the name and creation date over to the annotation that replaces ``source``."""
    name = name_of(source)
    if is_identity(name):
        set_name(target, name)
    created = (source.info or {}).get("creationDate", "")
    if created:
        target.set_info(creationDate=created)


def detach_replies(annot: fitz.Annot) -> list[int]:
    """Unlink the replies of ``annot`` (returning their xrefs) so that deleting it leaves them alone."""
    doc = _doc(annot)
    replies = [other.xref for other in annot.parent.annots() or [] if other.irt_xref == annot.xref]
    for xref in replies:
        doc.xref_set_key(xref, "IRT", "null")
    return replies


def attach_replies(doc: fitz.Document, replies: list[int], parent: fitz.Annot) -> None:
    for xref in replies:
        doc.xref_set_key(xref, "IRT", f"{parent.xref} 0 R")
