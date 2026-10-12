"""OCR endpoints: capabilities, start a background OCR job, poll job progress."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from .. import deps
from ..jobs import Job, JobManager
from ..pdf import doctools, ocr
from ..storage import PDF_LOCK, Mutation
from . import schemas
from .common import doc_info, ok

router = APIRouter(prefix="/api")
jobs = JobManager()
OCR_WORKERS = max(1, min(4, (os.cpu_count() or 2)))


@router.get("/ocr")
def capabilities() -> dict:
    langs = list(ocr.languages())
    return ok({"available": bool(ocr.tesseract_path() and langs), "languages": langs,
               "default": "eng" if "eng" in langs else (langs[0] if langs else None)})


def _ocr_work(doc_id: str, body: schemas.OcrBody, language: str) -> callable:
    store = deps.store()

    def work(job: Job) -> None:
        with PDF_LOCK:
            state, doc = store.open_current(doc_id)
            targets = doctools.resolve_pages(doc, body.pages)
            if not body.force:
                targets = [i for i in targets if not ocr.page_scan_info(doc[i])["hasOcr"]]
            tokens = {i: state.current.tokens[i] for i in targets}
        job.total = len(targets)
        if not targets:
            job.message = "All selected pages already have OCR text."
            job.result = {"pages": [], "words": 0, "skipped": []}
            job.document = doc_info(store.get(doc_id))
            return

        def recognise(index: int) -> tuple[int, list[ocr.OcrLine]]:
            with PDF_LOCK:
                _state, current = store.open_current(doc_id)
                png, zoom = ocr.render_for_ocr(current[index], body.dpi)
            lines = ocr.parse_tsv(ocr.run_tesseract(png, language, body.dpi), zoom)
            job.done += 1
            job.message = f"Recognised page {index + 1}"
            return index, lines

        with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
            results = dict(pool.map(recognise, targets))

        def apply(pdf) -> Mutation:
            latest = store.get(doc_id).current.tokens
            written, skipped, words = [], [], 0
            for index, lines in results.items():
                if index >= len(latest) or latest[index] != tokens[index]:
                    skipped.append(index)  # page changed while OCR was running
                    continue
                page = pdf[index]
                if body.force:
                    ocr.remove_invisible_text(page)
                words += ocr.write_text_layer(pdf, page, deps.catalog(), lines)
                written.append(index)
            return Mutation(changed=frozenset(written), result={"pages": written, "words": words, "skipped": skipped})

        new_state, result = store.mutate(doc_id, f"OCR ({len(targets)} page{'s' if len(targets) > 1 else ''})", apply)
        job.result = result
        job.document = doc_info(new_state)
        job.message = f"Recognised {result['words']} words on {len(result['pages'])} page(s)"

    return work


@router.post("/documents/{doc_id}/ocr")
def start_ocr(doc_id: str, body: schemas.OcrBody) -> dict:
    deps.store().get(doc_id)  # 404 if missing
    try:
        language = ocr.validate_language(body.language)
    except ocr.OcrError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        job = jobs.start(doc_id, "ocr", _ocr_work(doc_id, body, language),
                         (ocr.OcrError, doctools.ToolError))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok(job.to_json())


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return ok(job.to_json())
