"""Font files on disk: single fonts and collections (.ttc/.otc).

MuPDF (``fitz.Font``, ``insert_font``) and browsers only understand single-face
files, so a face inside a collection is extracted, once and on first use, into
its own ``.ttf``/``.otf`` file in a cache directory.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont, TTLibError

log = logging.getLogger(__name__)

SINGLE_EXTENSIONS = {".ttf", ".otf"}
COLLECTION_EXTENSIONS = {".ttc", ".otc"}
FONT_EXTENSIONS = SINGLE_EXTENSIONS | COLLECTION_EXTENSIONS

_READ_ERRORS = (TTLibError, OSError, KeyError, AssertionError, ValueError, IndexError)
_extract_lock = threading.Lock()


def is_collection(path: str | Path) -> bool:
    return Path(path).suffix.lower() in COLLECTION_EXTENSIONS


def open_faces(path: Path) -> Iterator[tuple[int, TTFont]]:
    """Yield (index, lazily loaded font) for every face in the file.

    The faces of a collection share one file handle, closed after the last face.
    """
    try:
        holder = TTCollection(str(path), lazy=True) if is_collection(path) else TTFont(str(path), lazy=True)
    except _READ_ERRORS:
        return
    try:
        yield from enumerate(holder.fonts) if isinstance(holder, TTCollection) else [(0, holder)]
    finally:
        holder.close()


def face_file(path: str, index: int, cache_dir: Path | None) -> str:
    """A single-face file for face ``index`` of ``path`` (the file itself unless a collection)."""
    if not is_collection(path):
        return path
    source = Path(path)
    stat = source.stat()
    directory = cache_dir or Path(tempfile.gettempdir()) / "pdfstudio-faces"
    stem = f"{source.stem}-{index}-{stat.st_size}-{int(stat.st_mtime)}"
    with _extract_lock:
        for suffix in (".otf", ".ttf"):
            existing = directory / f"{stem}{suffix}"
            if existing.exists():
                return str(existing)
        return str(_extract(source, index, directory, stem))


def _extract(source: Path, index: int, directory: Path, stem: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    collection = TTCollection(str(source), lazy=True)
    font = collection.fonts[index]
    target = directory / f"{stem}{'.otf' if font.sfntVersion == 'OTTO' else '.ttf'}"
    handle, temp = tempfile.mkstemp(dir=directory, suffix=".part")
    try:
        with os.fdopen(handle, "wb") as out:
            font.save(out)
        os.replace(temp, target)  # atomic: concurrent readers never see a partial file
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    log.info("Extracted face %d of %s to %s", index, source, target)
    return target
