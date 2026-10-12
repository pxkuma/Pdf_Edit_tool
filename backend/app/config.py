from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def user_fonts_dir(self) -> Path:
        return self.data_dir / "fonts"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_settings() -> Settings:
    base = Path(__file__).resolve().parent.parent
    data_dir = Path(os.environ.get("PDF_STUDIO_DATA", base / "data"))
    fonts = os.environ.get("PDF_STUDIO_FONT_DIRS", "/usr/share/fonts:/usr/local/share/fonts")
    return Settings(
        data_dir=data_dir,
        static_dir=Path(os.environ.get("PDF_STUDIO_STATIC", base / "static")),
        font_dirs=tuple(Path(p) for p in fonts.split(":") if p) + (data_dir / "fonts",),
        max_upload_mb=_int_env("PDF_STUDIO_MAX_UPLOAD_MB", 200),
        max_history=_int_env("PDF_STUDIO_MAX_HISTORY", 60),
        doc_ttl_hours=_int_env("PDF_STUDIO_DOC_TTL_HOURS", 72),
    )
