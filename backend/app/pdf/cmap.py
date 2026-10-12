"""Parsing of PDF character maps.

Embedded fonts in real-world PDFs are almost always subsetted and frequently lack
a usable Unicode cmap. To re-use such a font for new text we invert the font's
mapping *code -> unicode* (ToUnicode CMap or the simple-font /Encoding) into
*unicode -> code*, so we can emit the exact byte codes the font understands.
"""

from __future__ import annotations

import re

import pymupdf as fitz

_HEX = r"<([0-9A-Fa-f\s]*)>"
_BFCHAR_BLOCK = re.compile(r"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE_BLOCK = re.compile(r"beginbfrange(.*?)endbfrange", re.S)
_BFCHAR_ENTRY = re.compile(_HEX + r"\s*" + _HEX)
_BFRANGE_ENTRY = re.compile(_HEX + r"\s*" + _HEX + r"\s*(<[0-9A-Fa-f\s]*>|\[[^\]]*\])")
_CODESPACE = re.compile(r"begincodespacerange(.*?)endcodespacerange", re.S)

# Upper bound for a single bfrange, protects against malformed/hostile CMaps.
_MAX_RANGE = 0x10000


def _hex_to_bytes(value: str) -> bytes:
    cleaned = re.sub(r"\s", "", value)
    if len(cleaned) % 2:
        cleaned += "0"
    return bytes.fromhex(cleaned)


def _utf16_to_str(raw: bytes) -> str:
    if not raw:
        return ""
    if len(raw) % 2:
        raw = raw + b"\x00"
    try:
        return raw.decode("utf-16-be", errors="ignore")
    except UnicodeDecodeError:
        return ""


def _increment(dst: bytes, offset: int) -> bytes:
    """Return dst interpreted as big-endian integer plus offset (same length)."""
    value = int.from_bytes(dst, "big") + offset
    length = max(len(dst), 1)
    return (value % (1 << (8 * length))).to_bytes(length, "big")


def code_width(cmap_text: str) -> int:
    """Byte width of character codes declared by the codespace range (1 or 2)."""
    match = _CODESPACE.search(cmap_text)
    if not match:
        return 2
    first = re.search(_HEX, match.group(1))
    if not first:
        return 2
    return max(1, len(_hex_to_bytes(first.group(1))))


def parse_tounicode(cmap_text: str) -> dict[bytes, str]:
    """Parse a ToUnicode CMap into a mapping code bytes -> unicode string."""
    mapping: dict[bytes, str] = {}
    for block in _BFCHAR_BLOCK.findall(cmap_text):
        for src, dst in _BFCHAR_ENTRY.findall(block):
            text = _utf16_to_str(_hex_to_bytes(dst))
            if text:
                mapping[_hex_to_bytes(src)] = text
    for block in _BFRANGE_BLOCK.findall(cmap_text):
        for lo, hi, dst in _BFRANGE_ENTRY.findall(block):
            _add_range(mapping, _hex_to_bytes(lo), _hex_to_bytes(hi), dst)
    return mapping


def _add_range(mapping: dict[bytes, str], lo: bytes, hi: bytes, dst: str) -> None:
    width = len(lo)
    start, end = int.from_bytes(lo, "big"), int.from_bytes(hi, "big")
    if end < start or end - start > _MAX_RANGE:
        return
    if dst.startswith("["):
        targets = re.findall(_HEX, dst)
        for index, target in enumerate(targets):
            if start + index > end:
                break
            text = _utf16_to_str(_hex_to_bytes(target))
            if text:
                mapping[(start + index).to_bytes(width, "big")] = text
        return
    base = _hex_to_bytes(dst.strip("<>"))
    for offset in range(end - start + 1):
        text = _utf16_to_str(_increment(base, offset))
        if text:
            mapping[(start + offset).to_bytes(width, "big")] = text


def _base_encoding_table(name: str) -> dict[int, str]:
    codec = {
        "WinAnsiEncoding": "cp1252",
        "MacRomanEncoding": "mac_roman",
        "StandardEncoding": "latin-1",
        "PDFDocEncoding": "latin-1",
    }.get(name, "cp1252")
    table: dict[int, str] = {}
    for code in range(32, 256):
        try:
            char = bytes([code]).decode(codec)
        except UnicodeDecodeError:
            continue
        if char.isprintable():
            table[code] = char
    return table


def _glyph_to_unicode(glyph: str) -> str:
    try:
        value = fitz.glyph_name_to_unicode(glyph)
    except Exception:  # noqa: BLE001 - PyMuPDF raises generic errors here
        value = 0xFFFD
    if value and value != 0xFFFD and value > 0:
        return chr(value)
    match = re.fullmatch(r"(?:uni|u)([0-9A-Fa-f]{4,6})", glyph)
    if match:
        return chr(int(match.group(1), 16))
    return ""


def parse_differences(differences: str) -> dict[int, str]:
    """Parse an /Differences array: ``[ 32 /space /exclam 65 /A ]``."""
    result: dict[int, str] = {}
    code = 0
    for token in re.findall(r"/[^\s/\[\]]+|\d+", differences):
        if token.startswith("/"):
            char = _glyph_to_unicode(token[1:].replace("#20", " "))
            if char:
                result[code] = char
            code += 1
        else:
            code = int(token)
    return result


def simple_encoding_map(base_name: str, differences: str | None) -> dict[bytes, str]:
    table = _base_encoding_table(base_name)
    if differences:
        table.update(parse_differences(differences))
    return {bytes([code]): char for code, char in table.items()}
