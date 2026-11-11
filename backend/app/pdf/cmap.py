"""Parsing of PDF character maps.

Embedded fonts in real-world PDFs are almost always subsetted and frequently lack
a usable Unicode cmap. To re-use such a font for new text we invert the font's
mapping *code -> unicode* (ToUnicode CMap or the simple-font /Encoding) into
*unicode -> code*, so we can emit the exact byte codes the font understands.
"""

from __future__ import annotations

import re

from . import encodings

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


def _dest_text(value: str, offset: int = 0) -> str:
    """Decode a bfchar/bfrange destination (UTF-16BE), plus ``offset`` for ranges.

    UTF-16BE hex always has a multiple of 4 digits. Some producers (MuPDF 1.28
    among them) write characters outside the BMP as a bare 5- or 6-digit code
    point such as ``<1f600>``; those are read as code points.
    """
    cleaned = re.sub(r"\s", "", value)
    if len(cleaned) in (5, 6) and re.fullmatch(r"[0-9A-Fa-f]+", cleaned):
        point = int(cleaned, 16) + offset
        return chr(point) if point <= 0x10FFFF and not 0xD800 <= point <= 0xDFFF else ""
    text = _utf16_to_str(_hex_to_bytes(cleaned))
    if not offset or not text:
        return text
    # Ranges advance the last character: a code point (never a UTF-16 unit, so a
    # surrogate pair crosses <D83DDFFF> -> <D83EDC00>), and only the last one of
    # a multi-character destination such as a ligature.
    point = ord(text[-1]) + offset
    if point > 0x10FFFF or 0xD800 <= point <= 0xDFFF:
        return ""
    return text[:-1] + chr(point)


def _utf16_to_str(raw: bytes) -> str:
    if not raw:
        return ""
    if len(raw) % 2:
        raw = raw + b"\x00"
    try:
        return raw.decode("utf-16-be", errors="ignore")
    except UnicodeDecodeError:
        return ""


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
            text = _dest_text(dst)
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
            text = _dest_text(target)
            if text:
                mapping[(start + index).to_bytes(width, "big")] = text
        return
    base = dst.strip("<>")
    for offset in range(end - start + 1):
        text = _dest_text(base, offset)
        if text:
            mapping[(start + offset).to_bytes(width, "big")] = text


def parse_difference_names(differences: str) -> encodings.GlyphTable:
    """Parse an /Differences array: ``[ 32 /space /exclam 65 /A ]`` -> code -> glyph name."""
    result: encodings.GlyphTable = {}
    code = 0
    for token in re.findall(r"/[^\s/\[\]<>()]*|\d+", differences):
        if token.startswith("/"):
            if 0 <= code < 256:
                result[code] = _decode_name(token[1:])
            code += 1
        else:
            code = int(token)
    return result


def _decode_name(name: str) -> str:
    return re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), name)


def parse_differences(differences: str) -> dict[int, str]:
    """Parse an /Differences array into code -> unicode text."""
    return encodings.to_unicode_table(parse_difference_names(differences))


def simple_glyph_names(base: encodings.GlyphTable, differences: str | None) -> encodings.GlyphTable:
    table = dict(base)
    if differences:
        table.update(parse_difference_names(differences))
    return table


def simple_encoding_map(base_name: str, differences: str | None) -> dict[bytes, str]:
    """Code -> unicode for a named base encoding plus /Differences (unknown names: empty base)."""
    names = simple_glyph_names(encodings.base_glyph_table(base_name), differences)
    return glyph_table_to_map(names)


def glyph_table_to_map(names: encodings.GlyphTable) -> dict[bytes, str]:
    return {bytes([code]): text for code, text in encodings.to_unicode_table(names).items()}


_CMAP_HEADER = (
    "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
    "/CIDSystemInfo <</Registry(Adobe)/Ordering(UCS)/Supplement 0>> def\n"
    "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
)
_CMAP_FOOTER = "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
_CMAP_CHUNK = 100  # entries per bfchar/bfrange section (PDF limit)


def _utf16_hex(text: str) -> str:
    return text.encode("utf-16-be").hex().upper()


def _continues(code: bytes, text: str, prev_code: bytes, prev_text: str) -> bool:
    """Whether (code, text) extends a bfrange: only the last byte of both increments."""
    if code[:-1] != prev_code[:-1] or code[-1] != prev_code[-1] + 1:
        return False
    a, b = prev_text.encode("utf-16-be"), text.encode("utf-16-be")
    return len(a) == len(b) and a[:-1] == b[:-1] and b[-1] == a[-1] + 1


def build_tounicode(mapping: dict[bytes, str], code_bytes: int = 2) -> str:
    """A ToUnicode CMap for ``mapping`` (UTF-16BE destinations, surrogate pairs included)."""
    runs: list[list[tuple[bytes, str]]] = []
    for code, text in sorted(mapping.items()):
        if len(code) != code_bytes or not text:
            continue
        if runs and _continues(code, text, *runs[-1][-1]):
            runs[-1].append((code, text))
        else:
            runs.append([(code, text)])
    singles = [run[0] for run in runs if len(run) == 1]
    ranges = [run for run in runs if len(run) > 1]
    digits = 2 * code_bytes
    parts = [_CMAP_HEADER, f"1 begincodespacerange\n<{'0' * digits}> <{'F' * digits}>\nendcodespacerange\n"]
    for pos in range(0, len(ranges), _CMAP_CHUNK):
        chunk = ranges[pos:pos + _CMAP_CHUNK]
        body = "\n".join(f"<{r[0][0].hex().upper()}> <{r[-1][0].hex().upper()}> <{_utf16_hex(r[0][1])}>" for r in chunk)
        parts.append(f"{len(chunk)} beginbfrange\n{body}\nendbfrange\n")
    for pos in range(0, len(singles), _CMAP_CHUNK):
        chunk = singles[pos:pos + _CMAP_CHUNK]
        body = "\n".join(f"<{code.hex().upper()}> <{_utf16_hex(text)}>" for code, text in chunk)
        parts.append(f"{len(chunk)} beginbfchar\n{body}\nendbfchar\n")
    parts.append(_CMAP_FOOTER)
    return "".join(parts)
