"""Shared helpers for API routers."""

from __future__ import annotations

from typing import Any, Callable

import pymupdf as fitz
from fastapi import HTTPException, UploadFile

from .. import deps
from ..pdf.pages import page_info
from ..storage import PDF_LOCK, DocState, Mutation


def ok(data: Any = None) -> dict:
    return {"ok": True, "data": data}


def doc_info(state: DocState) -> dict:
    with PDF_LOCK:
        _state, doc = deps.store().open_current(state.id)
        pages = page_info(doc)
        metadata_title = (doc.metadata or {}).get("title", "")
        has_forms = bool(doc.is_form_pdf)
    for page, token in zip(pages, state.current.tokens):
        page["token"] = token
    return {
        "id": state.id,
        "filename": state.filename,
        "title": metadata_title,
        "pages": pages,
        "version": state.current.file,
        "canUndo": state.can_undo,
        "canRedo": state.can_redo,
        "cursor": state.cursor,
        "history": [{"label": v.label, "ts": v.ts} for v in state.versions],
        "wasEncrypted": state.was_encrypted,
        "hasForms": has_forms,
    }


def mutate(doc_id: str, label: str, operation: Callable[[fitz.Document], Mutation | None]) -> dict:
    state, result = deps.store().mutate(doc_id, label, operation)
    return ok({"document": doc_info(state), "result": result})


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
