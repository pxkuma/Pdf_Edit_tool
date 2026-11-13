"""Temporary storage for the second file of a document comparison.

The file is not a document: it has no history, is never listed or exported, and lives in its own
directory (``<data>/compare``) apart from the documents. A comparison session belongs to one open
document, is replaced when a new file is chosen for that document, and is deleted when the document
is closed or when it has not been used for ``ttl`` seconds.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pymupdf as fitz

from .storage import PDF_LOCK, load_upload, serialize

log = logging.getLogger(__name__)

SESSION_ID_RE = re.compile(r"^[a-f0-9]{32}$")
MAX_SESSIONS = 16  # across all documents; the least recently used one makes room
MAX_OPEN = 4  # parsed documents kept open for rendering


class CompareNotFound(LookupError):
    pass


@dataclass(frozen=True)
class CompareSession:
    id: str
    doc_id: str
    filename: str
    created: float
    pages: tuple[tuple[float, float], ...]  # (width, height) in points of every page of the second file

    def to_json(self) -> dict:
        return {"id": self.id, "docId": self.doc_id, "filename": self.filename, "created": self.created,
                "pageCount": len(self.pages),
                "pages": [{"index": i, "width": w, "height": h} for i, (w, h) in enumerate(self.pages)]}


class CompareStore:
    def __init__(self, root: Path, ttl_seconds: int, document_exists: Callable[[str], bool]) -> None:
        self.root = root
        self.ttl_seconds = ttl_seconds
        self._document_exists = document_exists
        self._lock = threading.RLock()
        self._open: dict[str, fitz.Document] = {}  # guarded by PDF_LOCK like every MuPDF object
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ paths
    def _dir(self, session_id: str) -> Path:
        if not SESSION_ID_RE.match(session_id or ""):
            raise CompareNotFound(session_id)
        return self.root / session_id

    def cache_dir(self, session_id: str) -> Path:
        path = self._dir(session_id) / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------ lifecycle
    def create(self, doc_id: str, filename: str, data: bytes, password: str | None = None) -> CompareSession:
        """Keep an uploaded file for comparing with ``doc_id``; the previous file of that document is dropped."""
        with PDF_LOCK:
            pdf, _encrypted = load_upload(data, password)
            try:
                payload = serialize(pdf)
                pages = tuple((round(p.rect.width, 2), round(p.rect.height, 2)) for p in pdf)
            finally:
                pdf.close()
        with self._lock:
            self.delete_for_document(doc_id)
            self._make_room()
            session = CompareSession(secrets.token_hex(16), doc_id, _clean_name(filename), time.time(), pages)
            directory = self._dir(session.id)
            directory.mkdir(parents=True)
            (directory / "other.pdf").write_bytes(payload)
            (directory / "session.json").write_text(json.dumps({
                "id": session.id, "doc_id": doc_id, "filename": session.filename, "created": session.created,
                "pages": [list(p) for p in pages]}))
            return session

    def get(self, session_id: str, doc_id: str) -> CompareSession:
        """The session, if it exists and belongs to ``doc_id``. Looking it up counts as using it."""
        path = self._dir(session_id) / "session.json"
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise CompareNotFound(session_id) from exc
        if raw.get("doc_id") != doc_id:
            raise CompareNotFound(session_id)
        path.touch()
        return CompareSession(raw["id"], raw["doc_id"], raw["filename"], raw["created"], tuple((w, h) for w, h in raw["pages"]))

    def delete(self, session_id: str) -> None:
        with self._lock:
            with PDF_LOCK:
                self._close(session_id)
            shutil.rmtree(self._dir(session_id), ignore_errors=True)

    def delete_for_document(self, doc_id: str) -> None:
        for session_id in self._sessions(doc_id):
            self.delete(session_id)

    def cleanup(self) -> int:
        """Delete sessions that expired or whose document is gone."""
        cutoff = time.time() - self.ttl_seconds
        removed = 0
        for session_id in self._sessions():
            path = self.root / session_id / "session.json"
            try:
                expired = path.stat().st_mtime < cutoff
                orphaned = not self._document_exists(json.loads(path.read_text()).get("doc_id", ""))
            except (OSError, ValueError):
                expired = orphaned = True  # a half-written or damaged session is of no use
            if expired or orphaned:
                self.delete(session_id)
                removed += 1
        return removed

    # ------------------------------------------------------------ reading
    def document(self, session_id: str) -> fitz.Document:
        """A cached handle on the second file. The caller must hold PDF_LOCK."""
        cached = self._open.get(session_id)
        if cached is not None:
            return cached
        path = self._dir(session_id) / "other.pdf"
        if not path.exists():
            raise CompareNotFound(session_id)
        doc = fitz.open(path)
        self._open[session_id] = doc
        while len(self._open) > MAX_OPEN:
            self._close(next(iter(self._open)))
        return doc

    def _close(self, session_id: str) -> None:
        doc = self._open.pop(session_id, None)
        if doc is not None:
            try:
                doc.close()
            except Exception:  # noqa: BLE001 - nothing to recover from a failed close
                log.warning("Could not close comparison file %s", session_id)

    # ------------------------------------------------------------ results
    def save_report(self, session_id: str, report: dict) -> None:
        path = self._dir(session_id) / "report.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report))
        tmp.replace(path)

    def load_report(self, session_id: str) -> dict | None:
        try:
            return json.loads((self._dir(session_id) / "report.json").read_text())
        except (OSError, ValueError):
            return None

    def has_report(self, session_id: str) -> bool:
        return (self._dir(session_id) / "report.json").exists()

    # ------------------------------------------------------------ housekeeping
    def _sessions(self, doc_id: str | None = None) -> list[str]:
        found = []
        for directory in self.root.iterdir():
            if not SESSION_ID_RE.match(directory.name):
                continue
            if doc_id is not None:
                try:
                    if json.loads((directory / "session.json").read_text()).get("doc_id") != doc_id:
                        continue
                except (OSError, ValueError):
                    continue
            found.append(directory.name)
        return found

    def _make_room(self) -> None:
        sessions = self._sessions()
        if len(sessions) < MAX_SESSIONS:
            return

        def last_used(session_id: str) -> float:
            try:
                return (self.root / session_id / "session.json").stat().st_mtime
            except OSError:
                return 0.0

        for session_id in sorted(sessions, key=last_used)[: len(sessions) - MAX_SESSIONS + 1]:
            self.delete(session_id)


def _clean_name(name: str) -> str:
    base = Path(name or "document.pdf").name
    return re.sub(r"[^\w\-. ()\[\]]+", "_", base).strip()[:150] or "document.pdf"
