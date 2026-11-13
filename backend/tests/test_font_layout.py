"""Line layout (audit C19: justified text under horizontal scaling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pdf import fontres, textedit
from app.pdf.fonts import FontCatalog
from app.pdf.textwriter import FontChain, TextStyle, line_width

TEXT = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> FontCatalog:
    cache = tmp_path_factory.mktemp("fonts") / "cache.json"
    return FontCatalog([Path("/usr/share/fonts"), Path("/usr/local/share/fonts")], cache)


@pytest.mark.parametrize("hscale", [60.0, 100.0, 150.0])
def test_justified_lines_fill_the_box_at_any_horizontal_scale(catalog, hscale):
    primary = catalog.substitute("Helvetica", False, False, False, False)
    chain = FontChain.build(catalog, None, primary, include_coverage=False)
    style = TextStyle(size=12, hscale=hscale)
    lines = textedit._layout(chain, TEXT, style, (72, 100), (1.0, 0.0), 200.0, 14, "justify")
    stretched = [line for line in lines[:-1] if line.space_extra]  # lines within the wrap tolerance stay
    assert stretched
    for line in stretched:
        assert line_width(line.glyphs, style, line.space_extra) == pytest.approx(200.0, abs=0.01)


def _subset_without_space(subtype: str = "TrueType", widths: dict[bytes, float] | None = None,
                          scale: float = 1.0) -> fontres.EmbeddedFont:
    return fontres.EmbeddedFont(xref=7, base_name="ABCDEF+Test", subtype=subtype, code_bytes=1,
                                reverse={"A": b"A"}, widths=widths or {}, width_scale=scale)


def test_missing_space_uses_the_embedded_space_width(catalog):
    # Producers often drop the space glyph but keep its /Widths entry (audit C13).
    embedded = _subset_without_space(widths={b"A": 600.0, b" ": 333.0})
    chain = FontChain.build(catalog, embedded, catalog.substitute("Helvetica", False, False, False, False))
    space = chain.encode("A A")[1]
    assert (space.font_key, space.width) == ("", 333.0)


def test_missing_space_of_a_type3_font_is_scaled_by_its_font_matrix(catalog):
    embedded = _subset_without_space("Type3", widths={b"A": 6.0, b" ": 3.0}, scale=100.0)
    chain = FontChain(embedded=embedded)
    assert chain.encode("A A")[1].width == 300.0


def test_missing_space_without_a_width_falls_back_to_the_substitute(catalog):
    primary = catalog.substitute("Helvetica", False, False, False, False)
    chain = FontChain.build(catalog, _subset_without_space(widths={b"A": 600.0}), primary)
    assert chain.encode("A A")[1].width == pytest.approx(catalog.open_font(primary).glyph_advance(32) * 1000)
