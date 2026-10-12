"""PDF Studio API + static frontend."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import deps
from .api import documents, edits, fonts, pages
from .pdf.annots import AnnotationError
from .pdf.doctools import ToolError
from .pdf.forms import FormError
from .pdf.images import ImageError
from .pdf.pages import PageError
from .pdf.textedit import TextEditError
from .storage import DocumentNotFound, InvalidDocument, PasswordRequired

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pdf-studio")

USER_ERRORS = (TextEditError, AnnotationError, ToolError, FormError, ImageError, PageError, InvalidDocument)


async def _cleanup_loop() -> None:
    cfg = deps.settings()
    while True:
        try:
            removed = await asyncio.to_thread(deps.store().cleanup_expired, cfg.doc_ttl_hours)
            if removed:
                log.info("Removed %d expired document(s)", removed)
        except Exception:  # noqa: BLE001 - never let the janitor die
            log.exception("Cleanup failed")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(deps.catalog().faces)  # warm the font catalog
    log.info("Font catalog ready: %d faces", len(deps.catalog().faces()))
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="PDF Studio", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


def _error(status: int, message: str, code: str = "error") -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": message, "code": code})


@app.exception_handler(DocumentNotFound)
async def _not_found(_request: Request, _exc: DocumentNotFound) -> JSONResponse:
    return _error(404, "Document not found. It may have expired - please open it again.", "not_found")


@app.exception_handler(PasswordRequired)
async def _password(_request: Request, _exc: PasswordRequired) -> JSONResponse:
    return _error(401, "This PDF is password protected. Enter the password to open it.", "password_required")


@app.exception_handler(HTTPException)
async def _http(_request: Request, exc: HTTPException) -> JSONResponse:
    return _error(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", [])[1:])
    return _error(422, f"Invalid input{(' for ' + where) if where else ''}: {first.get('msg', 'bad request')}", "validation")


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, USER_ERRORS):
        return _error(400, str(exc), "user_error")
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _error(500, "Something went wrong while processing the PDF. Your document was not changed.", "internal")


for error_type in USER_ERRORS:
    app.add_exception_handler(error_type, _unexpected)

app.include_router(documents.router)
app.include_router(pages.router)
app.include_router(edits.router)
app.include_router(fonts.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "data": {"status": "up"}}


_static = deps.settings().static_dir
if (_static / "assets").exists():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    candidate = (_static / path).resolve()
    if path and candidate.is_file() and _static.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = _static / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not built. Run the Docker image or `npm run build`.")
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
