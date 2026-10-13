"""Installed font catalog and user font uploads."""

from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import deps
from ..pdf import fontlib
from .common import ok, read_upload

router = APIRouter(prefix="/api/fonts")
MAX_FONT_BYTES = 30 * 1024 * 1024


@router.get("")
def list_fonts() -> dict:
    families = []
    for family, faces in sorted(deps.catalog().families().items(), key=lambda item: item[0].lower()):
        families.append({
            "family": family,
            "serif": faces[0].serif,
            "mono": faces[0].mono,
            "source": "user" if any(f.source == "user" for f in faces) else "system",
            "faces": [{"id": f.id, "style": f.style, "bold": f.bold, "italic": f.italic} for f in faces],
        })
    default = deps.default_face()
    return ok({"families": families, "default": default.id if default else None})


class FontDownloadBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.get("/lookup")
def lookup_font(name: str = Query(min_length=1, max_length=120)) -> dict:
    """Is the PDF font ``name`` installed, downloadable (free), commercial or unknown?"""
    result = fontlib.lookup(deps.catalog(), name)
    return ok({"name": result.name, "family": result.family, "status": result.status, "substitute": result.substitute})


@router.post("/download")
def download_font(body: FontDownloadBody) -> dict:
    """Install the free family of a PDF font so edits continue in that exact font."""
    catalog = deps.catalog()
    try:
        faces = fontlib.download(catalog, body.name, deps.settings().user_fonts_dir)
    except fontlib.FontLibraryOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except fontlib.FontLibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    weight, italic = fontlib.style_of(body.name)
    best = catalog.substitute(body.name, weight >= 600, italic, False, False)
    return ok({
        "family": faces[0].family,
        "face": best.id if best else faces[0].id,
        "faces": [{"id": f.id, "style": f.style} for f in faces],
    })


@router.get("/{face_id}/file")
def font_file(face_id: str) -> FileResponse:
    face = deps.catalog().get(face_id)
    if face is None:
        raise HTTPException(status_code=404, detail="Font not found.")
    media = "font/otf" if face.path.lower().endswith(".otf") else "font/ttf"
    return FileResponse(face.path, media_type=media, headers={"Cache-Control": "public, max-age=86400"})


@router.post("")
async def upload_font(file: UploadFile = File(...)) -> dict:
    data = await read_upload(file, MAX_FONT_BYTES, "font")
    name = file.filename or "font.ttf"
    suffix = ".otf" if name.lower().endswith(".otf") or data[:4] == b"OTTO" else ".ttf"
    if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise HTTPException(status_code=400, detail="Only TrueType (.ttf) and OpenType (.otf) fonts are supported.")
    stem = re.sub(r"[^\w\-]+", "_", name.rsplit(".", 1)[0])[:60] or "font"
    digest = hashlib.sha1(data).hexdigest()[:10]
    target = deps.settings().user_fonts_dir / f"{stem}-{digest}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    face = deps.catalog().add_user_font(target)
    if face is None:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="This font file could not be read.")
    return ok({"id": face.id, "family": face.family, "style": face.style})
