"""Content editing endpoints: text, annotations, images, forms, redaction, stamps."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, File, Form, UploadFile

from .. import deps
from ..pdf import annots, doctools, forms, images, textedit
from ..pdf.annots import AnnotStyle
from ..pdf.doctools import StampStyle
from ..pdf.textedit import BlockEdit, NewText, SpanEdit, StyleRequest
from ..storage import PDF_LOCK, Mutation
from . import schemas
from .common import check_page, mutate, ok, read_upload, single_page

router = APIRouter(prefix="/api/documents/{doc_id}")


def _style(body: schemas.StyleBody, require_font: bool = False) -> StyleRequest:
    values = body.model_dump()
    if require_font or values["font"] in ("", None):
        values["font"] = deps.font_or_default(values["font"])
    return StyleRequest(**values)


def _annot_style(body: schemas.AnnotStyleBody) -> AnnotStyle:
    return AnnotStyle(**body.model_dump())


def _stamp_style(body: schemas.StampStyleBody) -> StampStyle:
    values = body.model_dump()
    values["font"] = deps.font_or_default(values["font"])
    return StampStyle(**values)


def _preview(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 28 else text[:27] + "…"


# ------------------------------------------------------------------ text
@router.post("/text/span")
def edit_span(doc_id: str, body: schemas.SpanEditBody) -> dict:
    edit = SpanEdit(body.bbox, body.origin, body.original_text, body.text, _style(body.style),
                    body.dx, body.dy, body.fit_width, body.reflow, body.ocr_mode)
    operation = single_page(body.page, lambda doc, page: asdict(textedit.edit_span(doc, page, deps.catalog(), edit)))
    return mutate(doc_id, f"Edited text “{_preview(body.text)}”", operation)


@router.post("/text/block")
def edit_block(doc_id: str, body: schemas.BlockEditBody) -> dict:
    edit = BlockEdit(body.bbox, body.text, _style(body.style), body.align, body.line_height)
    operation = single_page(body.page, lambda doc, page: asdict(textedit.edit_block(doc, page, deps.catalog(), edit)))
    return mutate(doc_id, "Edited paragraph", operation)


@router.post("/text/add")
def add_text(doc_id: str, body: schemas.AddTextBody) -> dict:
    item = NewText(body.x, body.y, body.text, _style(body.style, require_font=True), body.width,
                   body.align, body.line_height, body.rotation)
    operation = single_page(body.page, lambda doc, page: asdict(textedit.add_text(doc, page, deps.catalog(), item)))
    return mutate(doc_id, f"Added text “{_preview(body.text)}”", operation)


@router.post("/text/replace")
def replace_text(doc_id: str, body: schemas.ReplaceBody) -> dict:
    def run(doc):
        pages = doctools.resolve_pages(doc, body.pages)
        result = doctools.replace_text(doc, deps.catalog(), body.query, body.replacement, pages,
                                       body.match_case, body.whole_word)
        return Mutation(changed=frozenset(result["pages"]), result=result)

    return mutate(doc_id, f"Replaced “{_preview(body.query)}”", run)


# ------------------------------------------------------------------ annotations
@router.post("/annotations")
def add_annotation(doc_id: str, body: schemas.AnnotationBody) -> dict:
    style = _annot_style(body.style)

    def operate(_doc, page):
        kind = body.kind
        if kind in annots.MARKUP:
            return annots.add_markup(page, kind, list(body.rects), style)
        if kind == "ink":
            return annots.add_ink(page, [list(p) for p in body.paths], style)
        if kind in annots.SHAPES:
            if body.start is None or body.end is None:
                raise annots.AnnotationError("Shape needs a start and end point.")
            return annots.add_shape(page, kind, body.start, body.end, style)
        if kind == "note":
            if body.point is None:
                raise annots.AnnotationError("Note needs a position.")
            return annots.add_note(page, body.point, AnnotStyle(**{**asdict(style), "contents": body.text or style.contents}), body.icon)
        if body.rect is None:
            raise annots.AnnotationError("Text box needs an area.")
        return annots.add_textbox(page, body.rect, body.text, body.font_size, style, body.text_color)

    return mutate(doc_id, f"Added {body.kind}", single_page(body.page, operate))


@router.patch("/annotations/{page}/{xref}")
def update_annotation(doc_id: str, page: int, xref: int, body: schemas.AnnotationUpdateBody) -> dict:
    operation = single_page(page, lambda _doc, pg: annots.update_annotation(pg, xref, _annot_style(body.style), body.rect))
    return mutate(doc_id, "Updated annotation", operation)


@router.delete("/annotations/{page}/{xref}")
def delete_annotation(doc_id: str, page: int, xref: int) -> dict:
    return mutate(doc_id, "Deleted annotation", single_page(page, lambda _doc, pg: annots.delete_annotation(pg, xref)))


# ------------------------------------------------------------------ images
@router.post("/images/{page}/{xref}/move")
def move_image(doc_id: str, page: int, xref: int, body: schemas.ImageMoveBody) -> dict:
    def run(doc):
        pg = check_page(doc, page)
        images.move_image(doc, pg, xref, body.rect)
        return Mutation(changed=None)  # other pages may share the image

    return mutate(doc_id, "Moved image", run)


@router.post("/images/{page}/{xref}/replace")
async def replace_image(doc_id: str, page: int, xref: int, file: UploadFile = File(...)) -> dict:
    data = await read_upload(file, images.MAX_IMAGE_BYTES, "image")

    def run(doc):
        images.replace_image(check_page(doc, page), xref, data)
        return Mutation(changed=None)

    return mutate(doc_id, "Replaced image", run)


@router.delete("/images/{page}/{xref}")
def delete_image(doc_id: str, page: int, xref: int) -> dict:
    def run(doc):
        images.delete_image(check_page(doc, page), xref)
        return Mutation(changed=None)

    return mutate(doc_id, "Deleted image", run)


# ------------------------------------------------------------------ forms
@router.get("/forms")
def list_forms(doc_id: str) -> dict:
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        return ok(forms.list_fields(doc))


@router.put("/forms")
def fill_forms(doc_id: str, body: schemas.FormValuesBody) -> dict:
    def run(doc):
        changed = forms.set_values(doc, [v.model_dump() for v in body.values])
        return Mutation(changed=frozenset(changed))

    return mutate(doc_id, "Filled form", run)


@router.post("/forms")
def add_field(doc_id: str, body: schemas.NewFieldBody) -> dict:
    operation = single_page(body.page, lambda _doc, pg: forms.add_field(pg, body.kind, body.rect, body.name, body.value))
    return mutate(doc_id, f"Added {body.kind} field", operation)


@router.delete("/forms/{page}/{xref}")
def delete_field(doc_id: str, page: int, xref: int) -> dict:
    def run(doc):
        forms.delete_field(doc, page, xref)
        return Mutation(changed=frozenset({page}))

    return mutate(doc_id, "Deleted form field", run)


@router.post("/flatten")
def flatten(doc_id: str, body: schemas.FlattenBody) -> dict:
    def run(doc):
        doc.bake(annots=body.annotations, widgets=body.forms)
        return Mutation(changed=None)

    return mutate(doc_id, "Flattened annotations/forms", run)


# ------------------------------------------------------------------ redaction & stamps
@router.post("/redact")
def redact(doc_id: str, body: schemas.RedactBody) -> dict:
    label = {"redact": "Redacted area", "whiteout": "Whiteout", "text": "Erased text"}[body.mode]
    operation = single_page(body.page, lambda doc, pg: doctools.redact(doc, pg, list(body.rects), body.mode, body.color))
    return mutate(doc_id, label, operation)


@router.post("/redact/search")
def redact_search(doc_id: str, body: schemas.RedactSearchBody) -> dict:
    def run(doc):
        result = doctools.redact_search(doc, body.query, doctools.resolve_pages(doc, body.pages), body.color)
        return Mutation(changed=frozenset(result["pages"]), result=result)

    return mutate(doc_id, f"Redacted “{_preview(body.query)}”", run)


@router.post("/watermark")
def watermark(doc_id: str, body: schemas.WatermarkBody) -> dict:
    def run(doc):
        pages = doctools.resolve_pages(doc, body.pages)
        doctools.watermark(doc, deps.catalog(), pages, body.text, _stamp_style(body.style), body.angle, body.layout)
        return Mutation(changed=frozenset(pages))

    return mutate(doc_id, "Added watermark", run)


@router.post("/watermark/image")
async def image_watermark(doc_id: str, file: UploadFile = File(...), pages: str = Form(""),
                          scale: float = Form(0.5), opacity: float = Form(0.3)) -> dict:
    data = await read_upload(file, images.MAX_IMAGE_BYTES, "image")
    scale = max(0.05, min(1.0, scale))
    opacity = max(0.02, min(1.0, opacity))

    def run(doc):
        targets = doctools.resolve_pages(doc, pages)
        doctools.image_watermark(doc, targets, data, scale, opacity)
        return Mutation(changed=frozenset(targets))

    return mutate(doc_id, "Added image watermark", run)


@router.post("/header-footer")
def header_footer(doc_id: str, body: schemas.HeaderFooterBody) -> dict:
    filename = deps.store().get(doc_id).filename

    def run(doc):
        pages = doctools.resolve_pages(doc, body.pages)
        doctools.header_footer(doc, deps.catalog(), pages, body.template, body.position, body.margin,
                               _stamp_style(body.style), body.start_number, filename)
        return Mutation(changed=frozenset(pages))

    return mutate(doc_id, "Added header/footer", run)
