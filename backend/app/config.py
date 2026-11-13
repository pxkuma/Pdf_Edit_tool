from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import paths


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    static_dir: Path
    font_dirs: tuple[Path, ...]
    max_upload_mb: int
    max_history: int
    doc_ttl_hours: int
    trust_roots_file: str | None = None  # extra PEM roots for signature validation (e.g. AATL)
    allow_private_tsa: bool = False  # let timestamp URLs point at private/loopback addresses

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def user_fonts_dir(self) -> Path:
        return self.data_dir / "fonts"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def _font_dirs(data_dir: Path) -> tuple[Path, ...]:
    configured = os.environ.get("PDF_STUDIO_FONT_DIRS")
    if configured:
        system = tuple(Path(p) for p in configured.split(os.pathsep) if p)
    else:
        system = paths.system_font_dirs()
    return system + (data_dir / "fonts",)


def load_settings() -> Settings:
    base = Path(__file__).resolve().parent.parent
    configured = os.environ.get("PDF_STUDIO_DATA")
    # A packaged build has no writable source tree, so it keeps its documents in the user's profile.
    data_dir = Path(configured) if configured else (paths.default_data_dir() if paths.is_frozen() else base / "data")
    static = os.environ.get("PDF_STUDIO_STATIC")
    return Settings(
        data_dir=data_dir,
        static_dir=Path(static) if static else paths.default_static_dir(base),
        font_dirs=_font_dirs(data_dir),
        max_upload_mb=_int_env("PDF_STUDIO_MAX_UPLOAD_MB", 200),
        max_history=_int_env("PDF_STUDIO_MAX_HISTORY", 60),
        doc_ttl_hours=_int_env("PDF_STUDIO_DOC_TTL_HOURS", 72),
        trust_roots_file=os.environ.get("PDF_STUDIO_TRUST_ROOTS") or None,
        allow_private_tsa=os.environ.get("PDF_STUDIO_ALLOW_PRIVATE_TSA", "").lower() in ("1", "true", "yes"),
    )
