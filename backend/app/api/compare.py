"""Compare the open document with a second PDF. Nothing here changes either document."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import deps
from ..compare_store import CompareNotFound, CompareSession
from ..jobs import Job
from ..pdf.compare import CompareError, CompareOptions, compare_documents
from ..storage import PDF_LOCK
from .common import check_page, ok, read_upload
from .ocr import jobs
from .pages import _matrix, _scale_bucket, render_bucket

router = APIRouter(prefix="/api/documents/{doc_id}/compare")

RENDER_CACHE = "private, max-age=3600"


class CompareBody(BaseModel):
    mode: Literal["text", "visual", "both"] = "both"
    dpi: int = Field(72, ge=36, le=150)  # resolution of the visual comparison
    sensitivity: Literal["low", "medium", "high"] = "medium"
    ignore_case: bool = False


def _session(doc_id: str, session_id: str) -> CompareSession:
    deps.store().get(doc_id)  # 404 when the document is gone
    try:
        return deps.compare_store().get(session_id, doc_id)
    except CompareNotFound as exc:
        raise HTTPException(status_code=404, detail="This comparison has expired. Choose the file to compare with again.") from exc


def _described(session: CompareSession) -> dict:
    return {**session.to_json(), "hasReport": deps.compare_store().has_report(session.id)}


@router.post("")
async def choose_file(doc_id: str, file: UploadFile = File(...), password: str | None = Form(None)) -> dict:
    """Upload the file to compare the document with. It is kept temporarily and never becomes a document."""
    deps.store().get(doc_id)
    data = await read_upload(file, deps.settings().max_upload_bytes, "file")
    sessions = deps.compare_store()
    session = await run_in_threadpool(sessions.create, doc_id, file.filename or "document.pdf", data, password)
    return ok(_described(session))


@router.get("/{session_id}")
def describe(doc_id: str, session_id: str) -> dict:
    return ok(_described(_session(doc_id, session_id)))


@router.delete("/{session_id}")
def close(doc_id: str, session_id: str) -> dict:
    deps.store().get(doc_id)
    deps.compare_store().delete(session_id)
    return ok()


def _compare_work(doc_id: str, session: CompareSession, options: CompareOptions):
    store, sessions = deps.store(), deps.compare_store()
    state = store.get(doc_id)
    version = state.current.file
    base = {"filename": state.filename, "pages": len(state.current.tokens)}
    other = {"filename": session.filename, "pages": len(session.pages)}

    def first():  # called with PDF_LOCK held
        current, doc = store.open_current(doc_id)
        if current.current.file != version:
            raise CompareError("The document changed while it was being compared. Run the comparison again.")
        return doc

    def second():
        try:
            return sessions.document(session.id)
        except CompareNotFound as exc:
            raise CompareError("The comparison was closed.") from exc

    def work(job: Job) -> None:
        report = compare_documents(first, second, options, PDF_LOCK, job)
        totals = report["totals"]
        report = {**report, "baseVersion": version, "base": base, "other": other}
        sessions.save_report(session.id, report)
        job.result = totals
        job.message = f"{totals['changes']} change(s) on {totals['pagesWithChanges']} page(s)"

    return work


@router.post("/{session_id}/run")
def run(doc_id: str, session_id: str, body: CompareBody) -> dict:
    session = _session(doc_id, session_id)
    options = CompareOptions(mode=body.mode, dpi=body.dpi, sensitivity=body.sensitivity, ignore_case=body.ignore_case)
    try:
        job = jobs.start(doc_id, "compare", _compare_work(doc_id, session, options), (CompareError,))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok(job.to_json())


@router.get("/{session_id}/report")
def report(doc_id: str, session_id: str) -> dict:
    session = _session(doc_id, session_id)
    found = deps.compare_store().load_report(session.id)
    if found is None:
        raise HTTPException(status_code=404, detail="Run the comparison first.")
    return ok(found)


@router.get("/{session_id}/pages/{index}/render")
def render_other(doc_id: str, session_id: str, index: int, scale: float = 1.0) -> Response:
    """A page of the second file as a PNG (same sizes and limits as rendering a page of the document)."""
    session = _session(doc_id, session_id)
    sessions = deps.compare_store()
    with PDF_LOCK:
        page = check_page(sessions.document(session.id), index)
        bucket = render_bucket(page.rect, _scale_bucket(scale))
        target = sessions.cache_dir(session.id) / f"{index}-{bucket}.png"
        if not target.exists():
            pix = page.get_pixmap(matrix=_matrix(bucket), alpha=False, annots=True)
            tmp = target.with_suffix(".tmp")
            pix.save(str(tmp), output="png")
            tmp.replace(target)
    return FileResponse(target, media_type="image/png", headers={"Cache-Control": RENDER_CACHE})
