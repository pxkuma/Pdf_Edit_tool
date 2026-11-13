# PyInstaller spec for the PDF Studio desktop build.
#
#   pyinstaller packaging/pdfstudio.spec
#
# Expects the web UI to be built first (frontend/dist). Produces a single
# console executable in dist/ (PDFStudio.exe on Windows) that serves the UI
# and the API on http://localhost:8080 and opens the browser.

import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - SPECPATH is injected by PyInstaller
FRONTEND_DIST = os.path.join(ROOT, "frontend", "dist")

if not os.path.isfile(os.path.join(FRONTEND_DIST, "index.html")):
    raise SystemExit("frontend/dist is missing. Run `npm ci && npm run build` in frontend/ first.")

datas = [(FRONTEND_DIST, "static")]
# Package data these libraries load at runtime (trust lists, font resources, ...).
for package in ("pyhanko", "pyhanko_certvalidator", "fontTools"):
    datas += collect_data_files(package)

a = Analysis(  # noqa: F821
    [os.path.join(SPECPATH, "entry.py")],  # noqa: F821
    pathex=[os.path.join(ROOT, "backend")],
    datas=datas,
    hiddenimports=[
        # uvicorn picks these at runtime by string name; the launcher pins loop="asyncio", http="h11".
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "anyio._backends._asyncio",
        "multipart",
    ],
    excludes=["tkinter", "test", "unittest", "pydoc_data"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PDFStudio",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # the banner with the URL and the Ctrl+C hint lives here
    disable_windowed_traceback=False,
)
