"""Application singletons (settings, storage, font catalog)."""

from __future__ import annotations

from functools import lru_cache

from .config import Settings, load_settings
from .pdf.fonts import FontCatalog, FontFace
from .storage import DocumentStore


@lru_cache(maxsize=1)
def settings() -> Settings:
    return load_settings()


@lru_cache(maxsize=1)
def store() -> DocumentStore:
    cfg = settings()
    return DocumentStore(cfg.docs_dir, cfg.max_history)


@lru_cache(maxsize=1)
def catalog() -> FontCatalog:
    cfg = settings()
    cfg.user_fonts_dir.mkdir(parents=True, exist_ok=True)
    system_dirs = [d for d in cfg.font_dirs if d != cfg.user_fonts_dir]
    fonts = FontCatalog(system_dirs, cfg.data_dir / "font-cache.json")
    for path in sorted(cfg.user_fonts_dir.glob("*")):
        if path.suffix.lower() in (".ttf", ".otf"):
            fonts.add_user_font(path)
    return fonts


def default_face() -> FontFace | None:
    return catalog().substitute("Helvetica", False, False, False, False)


def font_or_default(font: str | None) -> str:
    """Resolve an empty/unknown font selector to the default sans-serif face."""
    if font and (font.startswith("doc:") or (font.startswith("face:") and len(font) > 5)):
        return font
    face = default_face()
    return f"face:{face.id}" if face else "face:"
