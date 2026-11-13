"""Serve the built web UI (the Vite ``dist`` folder) from the API server.

Used by the Docker image, ``run.py`` and the packaged Windows build alike, so one process serves
both the UI and ``/api`` on a single port.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Python takes MIME types from the Windows registry, where a stray entry (often left by editors or
# archivers) can map ``.js`` to ``text/plain``. Browsers then refuse to run the module scripts.
_WEB_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
}


def pin_web_mime_types() -> None:
    for suffix, media_type in _WEB_TYPES.items():
        mimetypes.add_type(media_type, suffix)


def is_built(static_dir: Path) -> bool:
    return (static_dir / "index.html").is_file()


def _file_inside(root: Path, relative: str) -> Path | None:
    """The file ``relative`` names below ``root`` (never one outside it), or None."""
    try:
        candidate = (root / relative).resolve()
        return candidate if candidate.is_file() and root in candidate.parents else None
    except (OSError, ValueError):  # names Windows or the OS cannot represent
        return None


def mount_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve ``static_dir`` and fall back to ``index.html`` for client-side routes.

    Register it after every API router: the catch-all route would shadow later ones.
    """
    pin_web_mime_types()
    root = static_dir.resolve()
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        if path and (file := _file_inside(root, path)):
            return FileResponse(file)
        index = root / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=404,
                detail="The web UI is not built. Run `npm run build` in frontend/ (or use `python run.py`).",
            )
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
