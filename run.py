#!/usr/bin/env python3
"""Run PDF Studio on this computer, without Docker:  python run.py

First run: creates a virtual environment in .venv, installs backend/requirements.txt into it and
builds the web UI (needs Node.js, unless a built UI is already there). Later runs start at once.
Then it starts the server on http://localhost:8080 and opens your browser.

Options (the rest, e.g. --port 9000 or --no-browser, go to the server):
  --no-venv      use the Python you started this with instead of .venv
  --rebuild-ui   rebuild the web UI even if it looks up to date

Only the standard library is used here, so it works before anything is installed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import NoReturn

MIN_PYTHON = (3, 11)
ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
REQUIREMENTS = BACKEND / "requirements.txt"
IMPORT_CHECK = "import fastapi, uvicorn, pymupdf, pyhanko, fontTools, multipart"
UI_INPUTS = (FRONTEND / "src", FRONTEND / "index.html", FRONTEND / "package-lock.json", FRONTEND / "vite.config.ts")


def fail(message: str, code: int = 1) -> NoReturn:
    print(f"\n{message}\n", file=sys.stderr)
    if sys.platform == "win32" and sys.stdin is not None and sys.stdin.isatty():  # keep a double-clicked window open
        input("Press Enter to close this window.")
    raise SystemExit(code)


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        have = ".".join(map(str, sys.version_info[:3]))
        want = ".".join(map(str, MIN_PYTHON))
        fail(f"PDF Studio needs Python {want} or newer (this is {have}).\nGet it from https://www.python.org/downloads/")


def venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def in_virtualenv() -> bool:
    return sys.prefix != sys.base_prefix


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def run_quiet(command: list[str]) -> bool:
    return subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def ensure_venv() -> Path:
    environment = ROOT / ".venv"
    python = venv_python(environment)
    if not python.exists():
        print("Creating the virtual environment in .venv (first run only)...", flush=True)
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(environment)
        except (OSError, subprocess.CalledProcessError) as exc:
            fail(f"Could not create a virtual environment: {exc}\nOn Debian/Ubuntu run: sudo apt install python3-venv")
    return python


def ensure_requirements(python: Path, stamp: Path | None) -> None:
    current = requirements_hash()
    recorded = stamp.read_text(encoding="utf-8").strip() if stamp is not None and stamp.exists() else None
    if run_quiet([str(python), "-c", IMPORT_CHECK]) and (stamp is None or recorded == current):
        return
    print("Installing PDF Studio's Python packages (first run only, needs internet)...", flush=True)
    command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)]
    if subprocess.run(command, check=False).returncode != 0:
        fail("Installing the Python packages failed. Check your internet connection and try again.\n"
             f"To retry by hand: {' '.join(command)}")
    if stamp is not None:
        stamp.write_text(current, encoding="utf-8")


def newest_mtime(paths: tuple[Path, ...]) -> float:
    newest = 0.0
    for path in paths:
        files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else []
        newest = max([newest, *(f.stat().st_mtime for f in files)])
    return newest


def built_ui() -> Path | None:
    configured = os.environ.get("PDF_STUDIO_STATIC")
    candidates = ([Path(configured)] if configured else []) + [BACKEND / "static", FRONTEND / "dist"]
    return next((c for c in candidates if (c / "index.html").is_file()), None)


def ui_is_stale(built: Path) -> bool:
    return built == FRONTEND / "dist" and newest_mtime(UI_INPUTS) > (built / "index.html").stat().st_mtime


def build_ui() -> None:
    npm = shutil.which("npm")
    if not npm:
        fail("The web UI has not been built, and building it needs Node.js (https://nodejs.org, LTS version).\n"
             "Install Node.js and run this again, or download a release that already contains the built UI.")
    print("Building the web UI (first run only)...", flush=True)
    steps = [[npm, "ci", "--no-audit", "--no-fund"], [npm, "run", "build"]]
    if (FRONTEND / "node_modules").is_dir():
        steps = steps[1:]
    for step in steps:
        if subprocess.run(step, cwd=FRONTEND, check=False).returncode != 0:
            fail(f"Building the web UI failed (`{' '.join(step[1:])}` in frontend/).")


def ensure_ui(force: bool) -> None:
    built = built_ui()
    if built is None or force:
        build_ui()
    elif ui_is_stale(built) and shutil.which("npm"):
        print("The web UI sources changed; rebuilding it...", flush=True)
        build_ui()


def start_server(python: Path, arguments: list[str]) -> int:
    command = [str(python), "-m", "app", *arguments]
    os.chdir(BACKEND)
    if sys.platform != "win32":
        os.execv(command[0], command)  # the server takes over this process, so Ctrl+C reaches it directly
    process = subprocess.Popen(command)  # Windows cannot replace a process: wait for the server instead
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            continue  # the console already sent Ctrl+C to the server; let it shut down cleanly


def main(argv: list[str]) -> int:
    check_python()
    use_venv = "--no-venv" not in argv and not os.environ.get("PDF_STUDIO_NO_VENV") and not in_virtualenv()
    rebuild = "--rebuild-ui" in argv
    forwarded = [a for a in argv if a not in ("--no-venv", "--rebuild-ui")]
    if use_venv:
        python = ensure_venv()
        ensure_requirements(python, ROOT / ".venv" / "pdf-studio-requirements.sha256")
    else:
        python = Path(sys.executable)
        ensure_requirements(python, None)
    ensure_ui(rebuild)
    return start_server(python, forwarded)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(0)
