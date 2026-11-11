"""Width and code tables of embedded fonts (audit C7, C8, C10, C11)."""

from __future__ import annotations

from fontkit import add_stream, descriptor, raw_page, tounicode

from app.pdf import cmap, fontres

HELLO = b"BT /F1 24 Tf 72 700 Td <0041> Tj ET"


def _font(setup):
    doc, page = raw_page("<<>>", HELLO, (setup,))
    return doc, page.get_fonts()[0][0]


def _type0(encoding: str = "Identity-H", widths: str = "/W [65 [600]]", pairs: dict[int, str] | None = None,
           code_bytes: int = 2, extra_objects: tuple[str, ...] = ()):
    def setup(doc, font_xref):
        refs = []
        for body in extra_objects:
            xref = doc.get_new_xref()
            doc.update_object(xref, body)
            refs.append(xref)
        desc = descriptor(doc, "Test")
        w = widths.format(*refs)
        cid = doc.get_new_xref()
        doc.update_object(cid, f"<</Type/Font/Subtype/CIDFontType2/BaseFont/Test/CIDSystemInfo"
                               f"<</Registry(Adobe)/Ordering(Identity)/Supplement 0>>/FontDescriptor {desc} 0 R {w}>>")
        tu = add_stream(doc, tounicode(pairs or {0x41: "A"}, code_bytes))
        doc.update_object(font_xref, f"<</Type/Font/Subtype/Type0/BaseFont/Test/Encoding/{encoding}"
                                     f"/DescendantFonts[{cid} 0 R]/ToUnicode {tu} 0 R>>")
    return setup


def test_missing_width_applies_to_codes_outside_the_widths_array():
    def setup(doc, font_xref):
        desc = descriptor(doc, "Test")
        doc.xref_set_key(desc, "MissingWidth", "444")
        tu = add_stream(doc, tounicode({0x41: "A", 0x42: "B"}))
        doc.update_object(font_xref, f"<</Type/Font/Subtype/TrueType/BaseFont/Test/FirstChar 65/LastChar 65"
                                     f"/Widths[600]/FontDescriptor {desc} 0 R/ToUnicode {tu} 0 R>>")

    doc, xref = _font(setup)
    font = fontres.analyze_font(doc, xref, verify=False)
    assert font.width_of(b"A") == 600
    assert font.width_of(b"B") == 444


def test_vertical_fonts_are_not_reused_for_writing():
    doc, xref = _font(_type0("Identity-V"))
    assert fontres.analyze_font(doc, xref).reverse == {}  # would be laid out horizontally
    assert fontres.analyze_font(doc, xref, verify=False).widths  # widths still serve text positions


def test_cid_widths_with_indirect_elements():
    widths = "/W [1 {0} 0 R 20 22 {1} 0 R]"
    doc, xref = _font(_type0(widths=widths, extra_objects=("[700 800]", "300")))
    parsed = fontres.analyze_font(doc, xref, verify=False).widths
    assert parsed == {b"\x00\x01": 700, b"\x00\x02": 800, b"\x00\x14": 300, b"\x00\x15": 300, b"\x00\x16": 300}


def test_cid_widths_beyond_two_bytes_do_not_crash():
    doc, xref = _font(_type0(widths="/W [65535 [500 600] 70000 70010 300]"))
    parsed = fontres.analyze_font(doc, xref, verify=False).widths
    assert parsed == {b"\xff\xff": 500}


def test_analyze_font_never_raises(monkeypatch):
    doc, xref = _font(_type0())

    def broken(*_args, **_kwargs):
        raise OverflowError("malformed font")

    monkeypatch.setattr(fontres, "_analyze_type0", broken)
    assert fontres.analyze_font(doc, xref) is None


def test_one_byte_tounicode_keys_of_a_two_byte_font_are_widened():
    doc, xref = _font(_type0(pairs={0x41: "A", 0x42: "B"}, code_bytes=1, widths="/W [65 [600 700]]"))
    font = fontres.analyze_font(doc, xref, verify=False)
    assert font.reverse == {"A": b"\x00\x41", "B": b"\x00\x42"}


def test_bfrange_destination_crosses_a_surrogate_boundary():
    text = ("begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange "
            "1 beginbfrange <0001> <0003> <D83DDFFF> endbfrange endcmap")
    parsed = cmap.parse_tounicode(text)
    assert parsed[b"\x00\x01"] == "\U0001F7FF"
    assert parsed[b"\x00\x02"] == "\U0001F800"
    assert parsed[b"\x00\x03"] == "\U0001F801"


def test_bfrange_with_ligature_destination_increments_the_last_character():
    text = ("begincmap 1 begincodespacerange <00> <FF> endcodespacerange "
            "1 beginbfrange <10> <11> <00660066> endbfrange endcmap")
    assert cmap.parse_tounicode(text) == {b"\x10": "ff", b"\x11": "fg"}

