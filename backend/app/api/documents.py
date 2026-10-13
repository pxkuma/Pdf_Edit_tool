"""Document lifecycle, history, export and document-level metadata."""

from __future__ import annotations

import io
import re
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from .. import deps
from ..pdf import doctools, textedit
from ..pdf.doctools import ExportOptions
from ..pdf.pages import extract as extract_pages
from ..storage import PDF_LOCK, Mutation
from . import schemas
from .common import doc_info, mutate, ok, read_upload

router = APIRouter(prefix="/api")


def _download(data: bytes, filename: str, media_type: str) -> Response:
    safe = re.sub(r'[^\w\-. ()]+', "_", filename) or "download"
    headers = {"Content-Disposition": f"attachment; filename=\"{safe}\"; filename*=UTF-8''{quote(filename)}"}
    return Response(content=data, media_type=media_type, headers=headers)


def _stem(filename: str) -> str:
    return re.sub(r"\.pdf$", "", filename, flags=re.I) or "document"


def _zip(files: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(name, data)
    return buffer.getvalue()


@router.post("/documents")
async def upload(file: UploadFile = File(...), password: str | None = Form(None)) -> dict:
    data = await read_upload(file, deps.settings().max_upload_bytes, "file")
    state = deps.store().create(file.filename or "document.pdf", data, password)
    return ok(doc_info(state))


@router.get("/documents/{doc_id}")
def info(doc_id: str) -> dict:
    return ok(doc_info(deps.store().get(doc_id)))


@router.delete("/documents/{doc_id}")
def close(doc_id: str) -> dict:
    deps.store().delete(doc_id)
    return ok()


@router.post("/documents/{doc_id}/undo")
def undo(doc_id: str) -> dict:
    return ok(doc_info(deps.store().undo(doc_id)))


@router.post("/documents/{doc_id}/redo")
def redo(doc_id: str) -> dict:
    return ok(doc_info(deps.store().redo(doc_id)))


@router.post("/documents/{doc_id}/history/{index}")
def jump(doc_id: str, index: int) -> dict:
    try:
        return ok(doc_info(deps.store().jump(doc_id, index)))
    except IndexError as exc:
        raise HTTPException(status_code=400, detail="No such history entry.") from exc


@router.post("/documents/{doc_id}/revert")
def revert(doc_id: str) -> dict:
    store = deps.store()
    state = store.replace_document(doc_id, "Reverted to original", store.original_bytes(doc_id))
    return ok({"document": doc_info(state), "result": None})


# ------------------------------------------------------------------ export
@router.post("/documents/{doc_id}/export")
def export(doc_id: str, body: schemas.ExportBody) -> Response:
    store = deps.store()
    state = store.get(doc_id)
    with PDF_LOCK:
        data = doctools.export_pdf(store.current_bytes(doc_id), ExportOptions(**body.model_dump()))
    return _download(data, state.filename if state.filename.lower().endswith(".pdf") else f"{state.filename}.pdf", "application/pdf")


@router.get("/documents/{doc_id}/original")
def original(doc_id: str) -> Response:
    state = deps.store().get(doc_id)
    return _download(deps.store().original_bytes(doc_id), f"{_stem(state.filename)}-original.pdf", "application/pdf")


@router.post("/documents/{doc_id}/export/images")
def export_images(doc_id: str, body: schemas.ExportImagesBody) -> Response:
    store = deps.store()
    with PDF_LOCK:
        state, doc = store.open_current(doc_id)
        pages = doctools.resolve_pages(doc, body.pages)
        if len(pages) > 500:
            raise HTTPException(status_code=400, detail="Export at most 500 pages as images at once.")
        files = doctools.page_images(doc, pages, body.dpi, body.format)
    if len(files) == 1:
        name, data = files[0]
        return _download(data, f"{_stem(state.filename)}-{name}", "image/png" if body.format == "png" else "image/jpeg")
    return _download(_zip(files), f"{_stem(state.filename)}-images.zip", "application/zip")


@router.post("/documents/{doc_id}/export/extract")
def export_extract(doc_id: str, body: schemas.ExtractBody) -> Response:
    with PDF_LOCK:
        state, doc = deps.store().open_current(doc_id)
        data = extract_pages(doc, doctools.resolve_pages(doc, body.pages))
    return _download(data, f"{_stem(state.filename)}-extract.pdf", "application/pdf")


@router.post("/documents/{doc_id}/export/split")
def export_split(doc_id: str, body: schemas.SplitBody) -> Response:
    with PDF_LOCK:
        state, doc = deps.store().open_current(doc_id)
        parts = doctools.split(doc, body.every)
    return _download(_zip(parts), f"{_stem(state.filename)}-split.zip", "application/zip")


@router.get("/documents/{doc_id}/export/text")
def export_text(doc_id: str) -> Response:
    with PDF_LOCK:
        state, doc = deps.store().open_current(doc_id)
        text = "\n\f".join(page.get_text() for page in doc)
    return _download(text.encode("utf-8"), f"{_stem(state.filename)}.txt", "text/plain; charset=utf-8")


# ------------------------------------------------------------------ metadata
@router.get("/documents/{doc_id}/metadata")
def get_metadata(doc_id: str) -> dict:
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        return ok(doctools.get_metadata(doc))


@router.put("/documents/{doc_id}/metadata")
def put_metadata(doc_id: str, body: schemas.MetadataBody) -> dict:
    def run(doc):
        doctools.set_metadata(doc, body.model_dump())
        return Mutation(changed=frozenset())

    return mutate(doc_id, "Edited document properties", run)


@router.get("/documents/{doc_id}/toc")
def get_toc(doc_id: str) -> dict:
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        return ok(doctools.get_toc(doc))


@router.put("/documents/{doc_id}/toc")
def put_toc(doc_id: str, body: schemas.TocBody) -> dict:
    def run(doc):
        doctools.set_toc(doc, [item.model_dump() for item in body.items])
        return Mutation(changed=frozenset())

    return mutate(doc_id, "Edited bookmarks", run)


@router.get("/documents/{doc_id}/fonts")
def document_fonts(doc_id: str) -> dict:
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        fonts = textedit.document_fonts(doc)
    catalog = deps.catalog()
    return ok([{**font, "installed": catalog.exact_family(font["name"]) is not None} for font in fonts])


@router.get("/documents/{doc_id}/search")
def search(doc_id: str, q: str = "") -> dict:
    if len(q) > 500:
        raise HTTPException(status_code=400, detail="Search text is too long.")
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        return ok(doctools.search(doc, q))
