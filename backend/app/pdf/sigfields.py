"""Signature fields as MuPDF sees them: where they are and whether they hold a signature.

This module only uses MuPDF, so the cheap questions ("is this document signed?", "where is field X?")
never pay for importing or running pyHanko.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf as fitz

from .geometry import Rect4, to_display_rect


@dataclass(frozen=True)
class SigField:
    name: str
    page: int
    rect: Rect4 | None  # display space; None for an invisible (zero-size) field
    signed: bool


def _visible(rect: fitz.Rect) -> bool:
    return rect.width > 0.5 and rect.height > 0.5


def signature_fields(doc: fitz.Document) -> list[SigField]:
    """Every signature widget in the document, in page order."""
    if not doc.is_pdf or (doc.get_sigflags() < 0 and not doc.is_form_pdf):
        return []
    found: list[SigField] = []
    for page in doc:
        for widget in page.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]):
            rect = fitz.Rect(widget.rect)
            found.append(SigField(
                name=widget.field_name or "",
                page=page.number,
                rect=to_display_rect(page, rect) if _visible(rect) else None,
                signed=bool(widget.is_signed),
            ))
    return found


def signed_count(doc: fitz.Document) -> int:
    """How many signature fields carry a signature. Cheap when the document has no signature flags."""
    if not doc.is_pdf or doc.get_sigflags() < 1:
        return 0
    return sum(1 for field in signature_fields(doc) if field.signed)


def all_field_names(doc: fitz.Document) -> set[str]:
    names: set[str] = set()
    if not doc.is_form_pdf:
        return names
    for page in doc:
        for widget in page.widgets():
            if widget.field_name:
                names.add(widget.field_name)
    return names


def unique_field_name(doc: fitz.Document, base: str = "Signature") -> str:
    taken = all_field_names(doc)
    number = 1
    while f"{base}{number}" in taken:
        number += 1
    return f"{base}{number}"
