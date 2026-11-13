"""Glyph verification of embedded subset fonts (audit C2, C3).

A mapping may only be re-used when the font program really draws that glyph:
otherwise the edit renders as .notdef/blank while claiming an exact font match.
"""

from __future__ import annotations

import io

from conftest import find_font
from fontkit import add_stream, cff_font, descriptor, raw_page, tounicode
from fontTools import subset
from fontTools.ttLib import TTFont

from app.pdf import fontres

HELLO = b"BT /F1 24 Tf 72 700 Td (ABC) Tj ET"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz "


def _letters_only_truetype() -> bytes:
    options = subset.Options()
    options.notdef_outline = True
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=LETTERS)
    font = TTFont(find_font("LiberationSans-Regular.ttf"))
    subsetter.subset(font)
    font["cmap"].tables = [t for t in font["cmap"].tables if (t.platformID, t.platEncID) == (3, 1)]
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def _simple_font(subtype: str, file_key: str, program: bytes, file_extra: str = "", encoding: str = "",
                 to_unicode: dict[int, str] | None = None, flags: int = 32):
    def setup(doc, font_xref):
        file_xref = add_stream(doc, program, file_extra)
        desc = descriptor(doc, "ABCDEF+Test", file_key, file_xref, flags)
        parts = [f"/Type/Font/Subtype/{subtype}/BaseFont/ABCDEF+Test/FontDescriptor {desc} 0 R",
                 "/FirstChar 32/LastChar 255/Widths[" + " ".join("500" for _ in range(32, 256)) + "]"]
        if encoding:
            parts.append(f"/Encoding {encoding}")
        if to_unicode:
            parts.append(f"/ToUnicode {add_stream(doc, tounicode(to_unicode))} 0 R")
        doc.update_object(font_xref, "<<" + "".join(parts) + ">>")

    doc, page = raw_page("<<>>", HELLO, (setup,))
    return fontres.analyze_font(doc, page.get_fonts()[0][0])


def test_truetype_glyphs_stripped_from_subset_are_missing():
    full_ascii = {code: chr(code) for code in range(32, 127)}
    font = _simple_font("TrueType", "FontFile2", _letters_only_truetype(), encoding="/WinAnsiEncoding",
                        to_unicode=full_ascii)
    assert [d for d in "0123456789" if d in font.reverse] == []
    assert all(ch in font.reverse for ch in "AZaz")


def test_truetype_without_tounicode_uses_encoding_names():
    font = _simple_font("TrueType", "FontFile2", _letters_only_truetype(), encoding="/WinAnsiEncoding")
    assert "5" not in font.reverse
    assert font.code_for("g") == b"g"


def test_bare_cff_subset_is_verified():
    program = cff_font(("A", "B"), empty=("C",))
    font = _simple_font("Type1", "FontFile3", program, "/Subtype/Type1C",
                        encoding="<</Differences[65/A/B/C/D]>>",
                        to_unicode={65: "A", 66: "B", 67: "C", 68: "D"})
    assert sorted(font.reverse) == ["A", "B"]


def test_bare_cff_builtin_encoding_without_encoding_entry():
    font = _simple_font("Type1", "FontFile3", cff_font(("A", "B")), "/Subtype/Type1C")
    assert sorted(font.reverse) == ["A", "B"]


def test_type1_program_is_verified():
    program = open(find_font("NimbusSans-Regular.t1"), "rb").read()
    cleartext = program.index(b"eexec") + 6
    font = _simple_font("Type1", "FontFile", program, f"/Length1 {cleartext}/Length2 {len(program) - cleartext}/Length3 0",
                        encoding="<</BaseEncoding/WinAnsiEncoding/Differences[200/uni4E2D]>>")
    assert font.code_for("A") == b"A"
    assert "中" not in font.reverse
