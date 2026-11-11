"""Shared helpers for API routers."""

from __future__ import annotations

from typing import Any, Callable

import pymupdf as fitz
from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from .. import deps
from ..pdf.pages import page_info
from ..pdf.sigfields import signed_count
from ..storage import PDF_LOCK, DocState, Mutation


def ok(data: Any = None) -> dict:
    return {"ok": True, "data": data}


def doc_info(state: DocState) -> dict:
    """Describe the document as one consistent snapshot.

    Another request (a second tab, a finishing OCR job) can land between a mutation and this call, so
    ``state`` only names the document: pages, tokens, cursor and history all come from the version that
    is current while the lock is held.
    """
    with PDF_LOCK:
        latest, doc = deps.store().open_current(state.id)
        pages = page_info(doc)
        metadata_title = (doc.metadata or {}).get("title", "")
        has_forms = bool(doc.is_form_pdf)
        signatures = signed_count(doc)
    for page, token in zip(pages, latest.current.tokens):
        page["token"] = token
    return {
        "id": latest.id,
        "filename": latest.filename,
        "title": metadata_title,
        "pages": pages,
        "version": latest.current.file,
        "canUndo": latest.can_undo,
        "canRedo": latest.can_redo,
        "cursor": latest.cursor,
        "history": [{"label": v.label, "ts": v.ts} for v in latest.versions],
        "wasEncrypted": latest.was_encrypted,
        "hasForms": has_forms,
        "signatures": signatures,
    }


def mutate(doc_id: str, label: str, operation: Callable[[fitz.Document], Mutation | None]) -> dict:
    state, result = deps.store().mutate(doc_id, label, operation)
    return ok({"document": doc_info(state), "result": result})


async def amutate(doc_id: str, label: str, operation: Callable[[fitz.Document], Mutation | None]) -> dict:
    """``mutate`` for ``async`` handlers: the PDF work and the global lock stay off the event loop."""
    return await run_in_threadpool(mutate, doc_id, label, operation)


def check_page(doc: fitz.Document, index: int) -> fitz.Page:
    if not 0 <= index < doc.page_count:
        raise HTTPException(status_code=400, detail="Page number out of range.")
    return doc[index]


async def read_upload(upload: UploadFile, limit: int, kind: str = "file") -> bytes:
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"The {kind} is larger than {limit // (1024 * 1024)} MB.")
    if not data:
        raise HTTPException(status_code=400, detail=f"The {kind} is empty.")
    return data


def single_page(index: int, operation: Callable[[fitz.Document, fitz.Page], Any]) -> Callable[[fitz.Document], Mutation]:
    """Wrap a page-level operation into a document mutation touching one page."""

    def run(doc: fitz.Document) -> Mutation:
        page = check_page(doc, index)
        result = operation(doc, page)
        return Mutation(changed=frozenset({index}), result=result)

    return run
