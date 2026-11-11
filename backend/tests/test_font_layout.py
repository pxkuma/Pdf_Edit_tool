"""Line layout (audit C19: justified text under horizontal scaling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pdf import textedit
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
