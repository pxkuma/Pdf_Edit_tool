"""Where things live on each platform: user data, installed fonts, the built web UI, Tesseract.

Nothing here assumes Linux. Every location can still be overridden with an environment variable
(``PDF_STUDIO_DATA``, ``PDF_STUDIO_FONT_DIRS``, ``PDF_STUDIO_STATIC``, ``PDF_STUDIO_TESSERACT``).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "PDF Studio"
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


def is_frozen() -> bool:
    """Running from a PyInstaller bundle rather than from source."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path | None:
    """Root of the unpacked PyInstaller bundle (None when running from source)."""
    root = getattr(sys, "_MEIPASS", None)
    return Path(root) if is_frozen() and root else None


def executable_dir() -> Path:
    """Folder of the packaged .exe, or of the Python interpreter when running from source."""
    return Path(sys.executable).resolve().parent


def default_data_dir() -> Path:
    """Per-user folder for documents, caches and uploaded fonts."""
    home = Path.home()
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / APP_NAME
    if MACOS:
        return home / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "pdf-studio"


def system_font_dirs() -> tuple[Path, ...]:
    """Folders searched for installed fonts (those that do not exist are skipped later)."""
    home = Path.home()
    if WINDOWS:
        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT") or r"C:\Windows"
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return (Path(windir) / "Fonts", Path(local) / "Microsoft" / "Windows" / "Fonts")
    if MACOS:
        return (Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library" / "Fonts")
    return (
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        home / ".local" / "share" / "fonts",
        home / ".fonts",
    )


def default_static_dir(backend_root: Path) -> Path:
    """The built web UI: the bundle's copy, the Docker layout, or a local ``npm run build``."""
    candidates: list[Path] = []
    bundle = bundle_dir()
    if bundle:
        candidates.append(bundle / "static")
    candidates.append(backend_root / "static")
    candidates.append(backend_root.parent / "frontend" / "dist")
    return next((c for c in candidates if (c / "index.html").is_file()), candidates[0])


def tesseract_candidates() -> list[Path]:
    """Places Tesseract is usually installed when it is not on ``PATH`` (the Windows installer never adds it)."""
    names = ("tesseract.exe",) if WINDOWS else ("tesseract",)
    folders: list[Path] = []
    if is_frozen():
        folders += [executable_dir() / "tesseract", executable_dir()]
    if WINDOWS:
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
            if os.environ.get(variable):
                folders.append(Path(os.environ[variable]) / "Tesseract-OCR")
        if os.environ.get("LOCALAPPDATA"):
            folders.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Tesseract-OCR")
    elif MACOS:
        folders += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/opt/local/bin")]
    return [folder / name for folder in folders for name in names]


def find_tesseract() -> str | None:
    """``PDF_STUDIO_TESSERACT`` (a file or its folder), then ``PATH``, then the usual install folders."""
    override = os.environ.get("PDF_STUDIO_TESSERACT")
    if override:
        path = Path(override)
        if path.is_dir():
            path = path / ("tesseract.exe" if WINDOWS else "tesseract")
        if path.is_file():
            return str(path)
    found = shutil.which("tesseract")
    if found:
        return found
    return next((str(c) for c in tesseract_candidates() if c.is_file()), None)
