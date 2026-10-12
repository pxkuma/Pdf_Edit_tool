"""Document storage with versioned history (undo/redo) and per-page revision tokens.

Every mutation writes a complete new version file. Each page carries a random
*token* that changes only when that page changes; the UI uses it as a cache key
so undo/redo instantly re-uses previously rendered images.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import pymupdf as fitz

log = logging.getLogger(__name__)

# PyMuPDF/MuPDF is not thread-safe: every access goes through this lock.
PDF_LOCK = threading.RLock()

DOC_ID_RE = re.compile(r"^[a-f0-9]{32}$")
MAX_HISTORY_BYTES = 1500 * 1024 * 1024


class DocumentNotFound(LookupError):
    pass


class PasswordRequired(PermissionError):
    pass


class InvalidDocument(ValueError):
    pass


@dataclass(frozen=True)
class Version:
    file: str
    label: str
    tokens: tuple[str, ...]
    ts: float
    size: int = 0


@dataclass(frozen=True)
class DocState:
    id: str
    filename: str
    created: float
    versions: tuple[Version, ...]
    cursor: int
    was_encrypted: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def current(self) -> Version:
        return self.versions[self.cursor]

    @property
    def can_undo(self) -> bool:
        return self.cursor > 0

    @property
    def can_redo(self) -> bool:
        return self.cursor < len(self.versions) - 1

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "created": self.created,
            "cursor": self.cursor,
            "was_encrypted": self.was_encrypted,
            "meta": self.meta,
            "versions": [asdict(v) | {"tokens": list(v.tokens)} for v in self.versions],
        }

    @classmethod
    def from_json(cls, data: dict) -> "DocState":
        versions = tuple(
            Version(v["file"], v["label"], tuple(v["tokens"]), v["ts"], v.get("size", 0))
            for v in data["versions"]
        )
        return cls(
            data["id"], data["filename"], data["created"], versions, data["cursor"],
            data.get("was_encrypted", False), data.get("meta", {}),
        )


@dataclass(frozen=True)
class Mutation:
    """Describes what an operation changed.

    ``changed``: indices (in the new document) of modified pages; None = all pages.
    ``page_map``: for each new page index, the old index it came from (None = new page).
    """

    changed: frozenset[int] | None = frozenset()
    page_map: tuple[int | None, ...] | None = None
    result: Any = None


def new_token() -> str:
    return secrets.token_hex(6)


def _sanitize_filename(name: str) -> str:
    base = Path(name or "document.pdf").name
    base = re.sub(r"[^\w\-. ()\[\]]+", "_", base).strip() or "document.pdf"
    return base[:150]


def _load_any(data: bytes, password: str | None) -> tuple[fitz.Document, bool]:
    try:
        doc = fitz.open(stream=data)
    except Exception as exc:  # noqa: BLE001 - MuPDF raises generic errors
        raise InvalidDocument("This file could not be opened as a PDF or image.") from exc
    encrypted = False
    if doc.needs_pass:
        encrypted = True
        if not password or not doc.authenticate(password):
            doc.close()
            raise PasswordRequired("This PDF is password protected.")
    if not doc.is_pdf:
        try:
            converted = fitz.open("pdf", doc.convert_to_pdf())
        except Exception as exc:  # noqa: BLE001
            raise InvalidDocument("This file type cannot be converted to PDF.") from exc
        doc.close()
        doc = converted
    if doc.page_count == 0:
        raise InvalidDocument("The document has no pages.")
    return doc, encrypted


def serialize(doc: fitz.Document) -> bytes:
    return doc.tobytes(garbage=1, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)


class DocumentStore:
    def __init__(self, root: Path, max_history: int) -> None:
        self.root = root
        self.max_history = max(2, max_history)
        self.root.mkdir(parents=True, exist_ok=True)
        self._open_cache: dict[str, tuple[str, fitz.Document]] = {}

    # ------------------------------------------------------------ paths
    def _dir(self, doc_id: str) -> Path:
        if not DOC_ID_RE.match(doc_id or ""):
            raise DocumentNotFound(doc_id)
        return self.root / doc_id

    def cache_dir(self, doc_id: str) -> Path:
        path = self._dir(doc_id) / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _state_path(self, doc_id: str) -> Path:
        return self._dir(doc_id) / "state.json"

    # ------------------------------------------------------------ state
    def get(self, doc_id: str) -> DocState:
        path = self._state_path(doc_id)
        if not path.exists():
            raise DocumentNotFound(doc_id)
        return DocState.from_json(json.loads(path.read_text()))

    def _save_state(self, state: DocState) -> None:
        path = self._state_path(state.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_json()))
        tmp.replace(path)

    def update_meta(self, doc_id: str, **values: Any) -> DocState:
        with PDF_LOCK:
            state = self.get(doc_id)
            updated = replace(state, meta={**state.meta, **values})
            self._save_state(updated)
            return updated

    # ------------------------------------------------------------ lifecycle
    def create(self, filename: str, data: bytes, password: str | None = None) -> DocState:
        with PDF_LOCK:
            doc, encrypted = _load_any(data, password)
            try:
                payload = serialize(doc)
                pages = doc.page_count
            finally:
                doc.close()
            doc_id = secrets.token_hex(16)
            directory = self._dir(doc_id)
            directory.mkdir(parents=True)
            (directory / "original.pdf").write_bytes(payload)
            version = Version("v0000.pdf", "Opened document", tuple(new_token() for _ in range(pages)), time.time(), len(payload))
            (directory / version.file).write_bytes(payload)
            state = DocState(doc_id, _sanitize_filename(filename), time.time(), (version,), 0, encrypted)
            self._save_state(state)
            return state

    def delete(self, doc_id: str) -> None:
        with PDF_LOCK:
            self._drop_cache(doc_id)
            directory = self._dir(doc_id)
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)

    def cleanup_expired(self, ttl_hours: int) -> int:
        cutoff = time.time() - ttl_hours * 3600
        removed = 0
        for directory in self.root.iterdir():
            if not DOC_ID_RE.match(directory.name):
                continue
            state_file = directory / "state.json"
            last = state_file.stat().st_mtime if state_file.exists() else directory.stat().st_mtime
            if last < cutoff:
                self.delete(directory.name)
                removed += 1
        return removed

    # ------------------------------------------------------------ reading
    def version_path(self, state: DocState, index: int | None = None) -> Path:
        version = state.versions[state.cursor if index is None else index]
        return self._dir(state.id) / version.file

    def open_current(self, doc_id: str) -> tuple[DocState, fitz.Document]:
        """Return a cached read-only handle. Caller must hold PDF_LOCK."""
        state = self.get(doc_id)
        cached = self._open_cache.get(doc_id)
        if cached and cached[0] == state.current.file:
            return state, cached[1]
        self._drop_cache(doc_id)
        doc = fitz.open(self.version_path(state))
        self._open_cache[doc_id] = (state.current.file, doc)
        if len(self._open_cache) > 8:
            oldest = next(iter(self._open_cache))
            self._drop_cache(oldest)
        return state, doc

    def _drop_cache(self, doc_id: str) -> None:
        cached = self._open_cache.pop(doc_id, None)
        if cached:
            try:
                cached[1].close()
            except Exception:  # noqa: BLE001
                pass

    def current_bytes(self, doc_id: str) -> bytes:
        state = self.get(doc_id)
        return self.version_path(state).read_bytes()

    def original_bytes(self, doc_id: str) -> bytes:
        return (self._dir(doc_id) / "original.pdf").read_bytes()

    # ------------------------------------------------------------ writing
    def mutate(self, doc_id: str, label: str, operation: Callable[[fitz.Document], Mutation | None]) -> tuple[DocState, Any]:
        with PDF_LOCK:
            state = self.get(doc_id)
            doc = fitz.open(self.version_path(state))
            try:
                old_count = doc.page_count
                mutation = operation(doc) or Mutation()
                if doc.page_count == 0:
                    raise InvalidDocument("A document must keep at least one page.")
                payload = serialize(doc)
                new_count = doc.page_count
            finally:
                doc.close()
            tokens = _next_tokens(state.current.tokens, old_count, new_count, mutation)
            new_state = self._append_version(state, label, payload, tokens)
            return new_state, mutation.result

    def _append_version(self, state: DocState, label: str, payload: bytes, tokens: tuple[str, ...]) -> DocState:
        directory = self._dir(state.id)
        kept = list(state.versions[: state.cursor + 1])
        for dropped in state.versions[state.cursor + 1:]:
            (directory / dropped.file).unlink(missing_ok=True)
        number = int(kept[-1].file[1:5]) + 1 if kept else 0
        version = Version(f"v{number % 10000:04d}.pdf", label[:80], tokens, time.time(), len(payload))
        (directory / version.file).write_bytes(payload)
        kept.append(version)
        while len(kept) > self.max_history or (len(kept) > 2 and sum(v.size for v in kept) > MAX_HISTORY_BYTES):
            (directory / kept.pop(0).file).unlink(missing_ok=True)
        new_state = replace(state, versions=tuple(kept), cursor=len(kept) - 1)
        self._save_state(new_state)
        return new_state

    def replace_document(self, doc_id: str, label: str, payload: bytes) -> DocState:
        """Install a completely new PDF payload as the next version."""
        with PDF_LOCK:
            state = self.get(doc_id)
            doc = fitz.open("pdf", payload)
            pages = doc.page_count
            doc.close()
            return self._append_version(state, label, payload, tuple(new_token() for _ in range(pages)))

    def jump(self, doc_id: str, index: int) -> DocState:
        with PDF_LOCK:
            state = self.get(doc_id)
            if not 0 <= index < len(state.versions):
                raise IndexError("No such version")
            new_state = replace(state, cursor=index)
            self._save_state(new_state)
            return new_state

    def undo(self, doc_id: str) -> DocState:
        state = self.get(doc_id)
        return self.jump(doc_id, state.cursor - 1) if state.can_undo else state

    def redo(self, doc_id: str) -> DocState:
        state = self.get(doc_id)
        return self.jump(doc_id, state.cursor + 1) if state.can_redo else state


def _next_tokens(old: tuple[str, ...], old_count: int, new_count: int, mutation: Mutation) -> tuple[str, ...]:
    page_map = mutation.page_map
    if page_map is None:
        page_map = tuple(range(new_count)) if old_count == new_count else tuple([None] * new_count)
    tokens = []
    for index in range(new_count):
        source = page_map[index] if index < len(page_map) else None
        unchanged = mutation.changed is not None and index not in mutation.changed
        if source is not None and 0 <= source < len(old) and unchanged:
            tokens.append(old[source])
        else:
            tokens.append(new_token())
    return tuple(tokens)
