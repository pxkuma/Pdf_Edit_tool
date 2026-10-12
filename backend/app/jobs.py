"""Background jobs (long-running work such as OCR) with progress reporting."""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

JOB_TTL_SECONDS = 3600


@dataclass
class Job:
    id: str
    doc_id: str
    kind: str
    total: int = 0
    done: int = 0
    status: str = "running"  # running | done | error
    message: str = ""
    error: str = ""
    result: Any = None
    document: dict | None = None
    created: float = field(default_factory=time.time)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "docId": self.doc_id,
            "kind": self.kind,
            "total": self.total,
            "done": self.done,
            "status": self.status,
            "message": self.message,
            "error": self.error,
            "result": self.result,
            "document": self.document,
        }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, doc_id: str, kind: str, work: Callable[[Job], None], user_errors: tuple[type, ...]) -> Job:
        job = Job(secrets.token_hex(8), doc_id, kind)
        with self._lock:
            self._prune()
            if any(j.doc_id == doc_id and j.kind == kind and j.status == "running" for j in self._jobs.values()):
                raise RuntimeError(f"A {kind} job is already running for this document.")
            self._jobs[job.id] = job

        def runner() -> None:
            try:
                work(job)
                job.status = "done"
            except user_errors as exc:
                job.status, job.error = "error", str(exc)
            except Exception:  # noqa: BLE001 - reported to the user, details logged
                log.exception("Job %s (%s) failed", job.id, kind)
                job.status, job.error = "error", "The job failed unexpectedly. Your document was not changed."

        threading.Thread(target=runner, name=f"job-{kind}-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _prune(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        for key in [k for k, j in self._jobs.items() if j.status != "running" and j.created < cutoff]:
            del self._jobs[key]
