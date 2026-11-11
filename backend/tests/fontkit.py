"""Builders for PDFs with hand-written font objects (simple fonts, CFF, Type1...).

``page.insert_font`` only ever produces Type0/Identity-H TrueType fonts; real
PDFs also use simple fonts with /Encoding, the standard 14 fonts, bare CFF and
Type1 programs. These helpers create such fonts directly as PDF objects.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import pymupdf as fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen

from app.pdf import extract

Setup = Callable[[fitz.Document, int], None]


def raw_page(font_obj: str, content: bytes, setups: tuple[Setup, ...] = ()) -> tuple[fitz.Document, fitz.Page]:
    """A one-page document whose /F1 font is the given object (``setups`` may rewrite it)."""
    doc = fitz.open()
    page = doc.new_page()
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, font_obj)
    for setup in setups:
        setup(doc, font_xref)
    doc.xref_set_key(page.xref, "Resources", f"<</Font<</F1 {font_xref} 0 R>>>>")
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, content)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    reopened = fitz.open("pdf", doc.tobytes())
    return reopened, reopened[0]


def add_stream(doc: fitz.Document, data: bytes, extra: str = "") -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, f"<<{extra}>>")
    doc.update_stream(xref, data)
    return xref


def tounicode(pairs: dict[int, str], code_bytes: int = 1) -> bytes:
    digits = 2 * code_bytes
    lines = "\n".join(f"<{code:0{digits}X}> <{text.encode('utf-16-be').hex().upper()}>" for code, text in pairs.items())
    low, high = "0" * digits, "F" * digits
    return (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapName /Test def "
        f"1 begincodespacerange <{low}> <{high}> endcodespacerange {len(pairs)} beginbfchar\n{lines}\n"
        "endbfchar endcmap CMapName currentdict /CMap defineresource pop end end"
    ).encode()


def descriptor(doc: fitz.Document, name: str, file_key: str | None = None, file_xref: int | None = None,
               flags: int = 32) -> int:
    file_part = f"/{file_key} {file_xref} 0 R" if file_key else ""
    xref = doc.get_new_xref()
    doc.update_object(xref, (
        f"<</Type/FontDescriptor/FontName/{name}/Flags {flags}/FontBBox[0 -200 1000 900]/ItalicAngle 0"
        f"/Ascent 900/Descent -200/CapHeight 700/StemV 80{file_part}>>"
    ))
    return xref


def spans(page: fitz.Page) -> list[dict]:
    model = extract.page_text_model(page)
    return [s for b in model["blocks"] for line in b["lines"] for s in line["spans"]]


def _box(pen: T2CharStringPen) -> None:
    pen.moveTo((50, 0))
    pen.lineTo((450, 0))
    pen.lineTo((450, 700))
    pen.lineTo((50, 700))
    pen.closePath()


def cff_font(drawn: tuple[str, ...], empty: tuple[str, ...] = ()) -> bytes:
    """A bare CFF program: ``drawn`` glyphs have a box outline, ``empty`` ones none."""
    order = [".notdef", *drawn, *empty]
    charstrings = {}
    for name in order:
        pen = T2CharStringPen(500, None)
        if name in drawn:
            _box(pen)
        charstrings[name] = pen.getCharString()
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({})
    builder.setupCFF("TestCFF", {"FullName": "TestCFF"}, charstrings, {})
    font = builder.font
    out = io.BytesIO()
    font["CFF "].cff.compile(out, font)
    return out.getvalue()
