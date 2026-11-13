"""Start PDF Studio on this computer, with no Docker.

``python run.py`` (from the repository), ``python -m app`` (from ``backend/``) and the packaged
Windows build all end up in :func:`main`: it serves the web UI and the API from one process on
http://localhost:8080 and opens the browser.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from . import paths

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
PORT_SEARCH_SPAN = 20  # how many ports above the default to try when it is taken
BROWSER_WAIT_SECONDS = 90
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
ANY_HOSTS = {"0.0.0.0", "::"}  # noqa: S104 - recognised only to print a usable URL


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _env_port() -> int:
    try:
        return int(os.environ.get("PDF_STUDIO_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pdf-studio", description="Run PDF Studio on this computer.")
    parser.add_argument("--host", default=os.environ.get("PDF_STUDIO_HOST", DEFAULT_HOST),
                        help="address to listen on (default %(default)s; 0.0.0.0 shares it on your network)")
    parser.add_argument("--port", type=int, default=_env_port(), help="port to listen on (default %(default)s)")
    parser.add_argument("--no-browser", action="store_true", default=_env_flag("PDF_STUDIO_NO_BROWSER"),
                        help="do not open the browser")
    parser.add_argument("--data-dir", help="where documents and caches are kept (default: your user data folder)")
    return parser


# --------------------------------------------------------------------------- ports
def _can_bind(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        if sys.platform != "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as uvicorn does; unsafe on Windows
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(host: str, preferred: int, search: int = PORT_SEARCH_SPAN) -> int | None:
    """``preferred`` if it is free, else the next free port above it (None if none is)."""
    return next((p for p in range(preferred, preferred + search + 1) if _can_bind(host, p)), None)


def _loopback(host: str) -> str:
    return "127.0.0.1" if host in ANY_HOSTS or host == "localhost" else host


def display_url(host: str, port: int) -> str:
    shown = "localhost" if host in ANY_HOSTS | LOCAL_HOSTS else host
    return f"http://{f'[{shown}]' if ':' in shown else shown}:{port}"


def is_pdf_studio(host: str, port: int, timeout: float = 1.5) -> bool:
    """Whether a PDF Studio server already answers on this port."""
    url = f"http://{_loopback(host)}:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed http URL
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return isinstance(payload, dict) and (payload.get("data") or {}).get("app") == "pdf-studio"


# --------------------------------------------------------------------------- browser
def _open_browser_when_ready(url: str, host: str, port: int) -> None:
    deadline = time.monotonic() + BROWSER_WAIT_SECONDS
    while time.monotonic() < deadline:
        if is_pdf_studio(host, port, timeout=1.0):
            webbrowser.open(url)
            return
        time.sleep(0.4)


def open_browser_soon(url: str, host: str, port: int) -> None:
    threading.Thread(target=_open_browser_when_ready, args=(url, host, port), daemon=True, name="open-browser").start()


# --------------------------------------------------------------------------- startup
def prepare_environment(data_dir: str | None) -> None:
    """Defaults the app reads at import time. Set them before importing ``app.main``."""
    if data_dir:
        os.environ["PDF_STUDIO_DATA"] = str(Path(data_dir).expanduser())
    else:
        os.environ.setdefault("PDF_STUDIO_DATA", str(paths.default_data_dir()))
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # one Tesseract thread per page; pages run in parallel


def ocr_status() -> str:
    from .pdf import ocr

    if not ocr.tesseract_path():
        return "OCR: off - " + ocr.INSTALL_HINT
    languages = ocr.languages()
    return f"OCR: on ({', '.join(languages)})" if languages else "OCR: off - Tesseract has no language data installed."


def print_banner(url: str, host: str, data_dir: str, static_dir: Path) -> None:
    lines = [
        "",
        "  PDF Studio is running",
        f"  Open     {url}",
        f"  Data     {data_dir}",
        f"  Web UI   {static_dir}",
        f"  {ocr_status()}",
    ]
    if host not in LOCAL_HOSTS:
        lines.append("  Warning  Reachable from other computers on your network; there is no login.")
    lines += ["", "  Press Ctrl+C (or close this window) to stop.", ""]
    print("\n".join(lines), flush=True)


def _make_console_safe() -> None:
    """Never crash on a character the Windows console code page cannot show."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")


def _server_options() -> dict:
    options: dict = {"ws": "none", "log_level": "info"}
    if paths.is_frozen():  # the bundle ships only the pure-Python pieces, named explicitly
        options.update(loop="asyncio", http="h11")
    if sys.stdout is None or sys.stderr is None:  # windowed build: no console to log to
        options["log_config"] = None
    return options


def serve(host: str, port: int) -> None:
    import uvicorn

    from .main import app

    uvicorn.run(app, host=host, port=port, **_server_options())


def run(args: argparse.Namespace) -> int:
    prepare_environment(args.data_dir)
    from . import deps
    from .frontend import is_built

    settings = deps.settings()
    if not is_built(settings.static_dir):
        print(f"The web UI is not built (no index.html in {settings.static_dir}).\n"
              "Run `python run.py` from the repository (it builds the UI), or `npm run build` in frontend/.",
              file=sys.stderr)
        return 2

    port = args.port
    if is_pdf_studio(args.host, port):
        url = display_url(args.host, port)
        print(f"PDF Studio is already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    chosen = port if _can_bind(args.host, port) else pick_port(args.host, port + 1)
    if chosen is None:
        print(f"No free port found from {port} to {port + PORT_SEARCH_SPAN}. Use --port to pick one.", file=sys.stderr)
        return 1
    if chosen != port:
        print(f"Port {port} is in use; using {chosen} instead.", flush=True)

    url = display_url(args.host, chosen)
    print_banner(url, args.host, str(settings.data_dir), settings.static_dir)
    if not args.no_browser:
        open_browser_soon(url, args.host, chosen)
    serve(args.host, chosen)
    print("PDF Studio stopped.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    _make_console_safe()
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001 - a double-clicked .exe would otherwise close before the error is read
        import traceback

        traceback.print_exc()
        if paths.is_frozen() and sys.stdin is not None and sys.stdin.isatty():
            input("\nPDF Studio could not start. Press Enter to close this window.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
