"""Redaction building blocks.

``redact_areas`` applies redactions for given areas while leaving the page's own ("marked for
redaction") Redact annotations untouched. ``clear_under`` deletes what a redaction cannot reach by
itself: comments, form fields and links sitting under the area. ``sanitize`` removes the
document-level traces: metadata, XMP, bookmarks, attachments, scripts and thumbnails.
"""

from __future__ import annotations

import pymupdf as fitz

# Annotation types that are never deleted by ``clear_under``: Redact marks are the user's own
# pending redactions, Popup windows are removed together with the comment they belong to.
_KEPT_TYPES = frozenset({fitz.PDF_ANNOT_REDACT, fitz.PDF_ANNOT_POPUP})
_PARKED_SUBTYPE = "/PdfStudioMarkedRedaction"
_MIN_EXTENT = 0.5  # annotation rectangles thinner than this (lines) are grown before testing


def redact_areas(page: fitz.Page, rects: list[fitz.Rect], fill: tuple | bool = False,
                 images: int = fitz.PDF_REDACT_IMAGE_NONE,
                 graphics: int = fitz.PDF_REDACT_LINE_ART_NONE,
                 text: int = fitz.PDF_REDACT_TEXT_REMOVE) -> None:
    """Apply redactions for ``rects`` without applying pre-existing Redact annotations.

    ``Page.apply_redactions`` consumes every Redact annotation on the page. Marked redactions that a
    user has not applied yet are parked under a different annotation subtype while it runs, so they
    come back exactly as they were (overlay text, colours, quads, appearance and all).
    """
    doc = page.parent
    parked = [annot.xref for annot in page.annots(types=[fitz.PDF_ANNOT_REDACT]) or []]
    for xref in parked:
        doc.xref_set_key(xref, "Subtype", _PARKED_SUBTYPE)
    try:
        for rect in rects:
            if not rect.is_empty:
                page.add_redact_annot(rect, fill=fill)
        page.apply_redactions(images=images, graphics=graphics, text=text)
    finally:
        for xref in parked:
            doc.xref_set_key(xref, "Subtype", "/Redact")


def clear_under(page: fitz.Page, rects: list[fitz.Rect]) -> dict[str, int]:
    """Delete annotations, form fields and links that overlap any of ``rects`` (page space).

    They cannot be clipped to the redacted area, and they may repeat the redacted content (comment
    text, field values, link addresses), so everything that overlaps is removed.
    """
    areas = [fitz.Rect(rect) for rect in rects if not fitz.Rect(rect).is_empty]
    return {
        "annotations": _delete_annotations(page, areas),
        "fields": _delete_fields(page, areas),
        "links": _delete_links(page, areas),
    }


def _hits(rect: fitz.Rect, areas: list[fitz.Rect]) -> bool:
    grown = fitz.Rect(rect)
    if grown.width < _MIN_EXTENT:
        grown.x0, grown.x1 = grown.x0 - _MIN_EXTENT, grown.x1 + _MIN_EXTENT
    if grown.height < _MIN_EXTENT:
        grown.y0, grown.y1 = grown.y0 - _MIN_EXTENT, grown.y1 + _MIN_EXTENT
    return any(grown.x0 < a.x1 and a.x0 < grown.x1 and grown.y0 < a.y1 and a.y0 < grown.y1 for a in areas)


def _delete_annotations(page: fitz.Page, areas: list[fitz.Rect]) -> int:
    doomed = [a for a in page.annots() or [] if a.type[0] not in _KEPT_TYPES and _hits(a.rect, areas)]
    for annot in doomed:
        page.delete_annot(annot)  # also removes the comment's popup window
    return len(doomed)


def _delete_fields(page: fitz.Page, areas: list[fitz.Rect]) -> int:
    doomed = {w.xref for w in page.widgets() or [] if _hits(w.rect, areas)}
    for widget in list(page.widgets() or []):
        if widget.xref in doomed:
            page.delete_widget(widget)
    return len(doomed)


def _link_rect(page: fitz.Page, link: dict) -> fitz.Rect:
    """A link's rectangle in page space. MuPDF reports links in display (rotated) space."""
    rect = fitz.Rect(link["from"]) * page.derotation_matrix
    rect.normalize()
    return rect


def _delete_links(page: fitz.Page, areas: list[fitz.Rect]) -> int:
    doomed = [link for link in page.get_links() if link.get("xref") and _hits(_link_rect(page, link), areas)]
    for link in doomed:
        page.delete_link(link)
    return len(doomed)


def sanitize(doc: fitz.Document) -> None:
    """Remove document-level traces that can still mention redacted content.

    Metadata (Info and XMP), bookmarks, attachments, document scripts and page thumbnails go. Page
    content, comments, form values, links and pending redaction marks are left alone.
    """
    doc.set_toc([])  # bookmark titles often repeat headings of the redacted text
    doc.scrub(attached_files=True, clean_pages=False, embedded_files=True, hidden_text=False, javascript=True,
              metadata=True, redactions=False, redact_images=0, remove_links=False, reset_fields=False,
              reset_responses=False, thumbnails=True, xml_metadata=True)
