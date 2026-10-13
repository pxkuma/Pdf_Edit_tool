"""Page rendering, page models and page organisation."""

from __future__ import annotations

from collections import OrderedDict

import pymupdf as fitz

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from .. import deps
from ..pdf import annots, extract, forms, images, ocr, pages
from ..storage import PDF_LOCK
from . import schemas
from .common import check_page, mutate, ok, read_upload, single_page

router = APIRouter(prefix="/api/documents/{doc_id}")

IMMUTABLE = "public, max-age=31536000, immutable"
NO_STORE = "no-store"
_MODEL_CACHE: OrderedDict[tuple[str, str, int], dict] = OrderedDict()
_MODEL_CACHE_SIZE = 300


def _scale_bucket(scale: float) -> int:
    """Quantize to 1/8 steps (stored as eighths) to keep the render cache small."""
    return max(1, min(64, round(scale * 8)))


@router.get("/pages/{index}/render")
def render(doc_id: str, index: int, scale: float = 1.0, t: str = "") -> Response:
    store = deps.store()
    bucket = _scale_bucket(scale)
    with PDF_LOCK:
        state, doc = store.open_current(doc_id)
        page = check_page(doc, index)
        token = state.current.tokens[index]
        target = store.cache_dir(doc_id) / f"{token}-{bucket}.png"
        if not target.exists():
            pix = page.get_pixmap(matrix=_matrix(bucket), alpha=False, annots=True)
            tmp = target.with_suffix(".tmp")
            pix.save(str(tmp), output="png")
            tmp.replace(target)
    cache = IMMUTABLE if t == token else NO_STORE
    return FileResponse(target, media_type="image/png", headers={"Cache-Control": cache})


def _matrix(bucket: int) -> fitz.Matrix:
    zoom = bucket / 8
    return fitz.Matrix(zoom, zoom)


@router.get("/pages/{index}/model")
def model(doc_id: str, index: int) -> dict:
    store = deps.store()
    with PDF_LOCK:
        state, doc = store.open_current(doc_id)
        page = check_page(doc, index)
        token = state.current.tokens[index]
        key = (doc_id, token, deps.catalog().version)
        cached = _MODEL_CACHE.get(key)
        if cached is None:
            cached = {
                "token": token,
                "text": _with_faces(extract.page_text_model(page)),
                "annotations": annots.list_annotations(page),
                "images": images.list_images(doc, page),
                "fields": forms.list_fields_on_page(page),
                "scan": ocr.page_scan_info(page),
            }
            _MODEL_CACHE[key] = cached
            while len(_MODEL_CACHE) > _MODEL_CACHE_SIZE:
                _MODEL_CACHE.popitem(last=False)
        else:
            _MODEL_CACHE.move_to_end(key)
    return ok(cached)


def _with_faces(model: dict) -> dict:
    """Attach the closest installed font to each span (used for live editing previews)."""
    memo: dict[tuple, tuple[str | None, bool]] = {}
    fonts = deps.catalog()
    for block in model["blocks"]:
        for line in block["lines"]:
            for span in line["spans"]:
                key = (span["font"], span["bold"], span["italic"], span["serif"], span["mono"])
                if key not in memo:
                    face = fonts.substitute(*key)
                    memo[key] = (face.id if face else None, fonts.exact_family(span["font"]) is not None)
                span["face"], span["installed"] = memo[key]
    return model


# ------------------------------------------------------------------ organise
@router.post("/pages/rotate")
def rotate(doc_id: str, body: schemas.RotateBody) -> dict:
    return mutate(doc_id, f"Rotated {len(body.pages)} page(s)", lambda doc: pages.rotate(doc, body.pages, body.angle))


@router.post("/pages/reorder")
def reorder(doc_id: str, body: schemas.ReorderBody) -> dict:
    return mutate(doc_id, "Reordered pages", lambda doc: pages.reorder(doc, body.order))


@router.post("/pages/delete")
def delete(doc_id: str, body: schemas.PagesBody) -> dict:
    return mutate(doc_id, f"Deleted {len(body.pages)} page(s)", lambda doc: pages.delete(doc, body.pages))


@router.post("/pages/duplicate")
def duplicate(doc_id: str, body: schemas.PagesBody) -> dict:
    return mutate(doc_id, f"Duplicated {len(body.pages)} page(s)", lambda doc: pages.duplicate(doc, body.pages))


@router.post("/pages/insert-blank")
def insert_blank(doc_id: str, body: schemas.InsertBlankBody) -> dict:
    def run(doc):
        size = None if body.size == "same" else body.size
        width = height = None
        if size and body.landscape:
            w, h = pages.PAPER_SIZES[size]
            width, height = h, w
        return pages.insert_blank(doc, body.at, size, width, height)

    return mutate(doc_id, "Inserted blank page", run)


@router.post("/pages/insert-file")
async def insert_file(doc_id: str, at: int = Form(...), file: UploadFile = File(...)) -> dict:
    data = await read_upload(file, deps.settings().max_upload_bytes, "file")
    name = (file.filename or "file").lower()
    is_image = (file.content_type or "").startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"))

    def run(doc):
        if is_image:
            return pages.insert_image_page(doc, data, at)
        return pages.insert_pdf(doc, data, at)

    return mutate(doc_id, f"Inserted {file.filename or 'file'}", run)


@router.post("/pages/crop")
def crop(doc_id: str, body: schemas.CropBody) -> dict:
    return mutate(doc_id, f"Cropped {len(body.pages)} page(s)", lambda doc: pages.crop(doc, body.pages, body.rect))


@router.post("/pages/reset-crop")
def reset_crop(doc_id: str, body: schemas.PagesBody) -> dict:
    return mutate(doc_id, "Removed crop", lambda doc: pages.reset_crop(doc, body.pages))


@router.get("/images/{xref}")
def image_file(doc_id: str, xref: int) -> Response:
    if xref <= 0:
        raise HTTPException(status_code=400, detail="Invalid image reference.")
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        if xref >= doc.xref_length():
            raise HTTPException(status_code=404, detail="Image not found.")
        data, mime = images.image_bytes(doc, xref)
    ext = "jpg" if mime == "image/jpeg" else "png"
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="image-{xref}.{ext}"'})


@router.post("/images")
async def add_image(doc_id: str, page: int = Form(...), rect: str = Form(...), file: UploadFile = File(...),
                    keep_proportion: bool = Form(True)) -> dict:
    data = await read_upload(file, images.MAX_IMAGE_BYTES, "image")
    target = _parse_rect(rect)

    operation = single_page(page, lambda _doc, pg: images.insert_image(pg, target, data, keep_proportion))
    return mutate(doc_id, "Added image", operation)


def _parse_rect(value: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(v) for v in value.split(",")]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid rectangle.") from exc
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="Invalid rectangle.")
    return (parts[0], parts[1], parts[2], parts[3])
