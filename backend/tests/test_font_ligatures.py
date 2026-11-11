"""Ligature glyphs in embedded subsets (audit C4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pdf import fontres
from app.pdf.fonts import FontCatalog
from app.pdf.textwriter import FontChain


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> FontCatalog:
    cache = tmp_path_factory.mktemp("fonts") / "cache.json"
    return FontCatalog([Path("/usr/share/fonts"), Path("/usr/local/share/fonts")], cache)


def _embedded(*chars: str) -> fontres.EmbeddedFont:
    reverse = {char: bytes([0, index + 1]) for index, char in enumerate(chars)}
    return fontres.EmbeddedFont(xref=99, base_name="ABCDEF+Minion", subtype="Type0", code_bytes=2,
                                reverse=reverse, widths={code: 500.0 for code in reverse.values()})


def test_ligature_only_subset_keeps_the_word_in_its_font(catalog):
    chain = FontChain.build(catalog, _embedded("ffi", "o", "c", "e"), None)
    glyphs = chain.encode("office")
    assert [g.char for g in glyphs] == ["o", "ffi", "c", "e"]
    assert {g.font_key for g in glyphs} == {"e99"}


def test_longest_ligature_wins_like_the_original_typesetting(catalog):
    chain = FontChain.build(catalog, _embedded("f", "i", "fi", "ffi", "n", "e", "o", "c"), None)
    assert [g.char for g in chain.encode("fine")] == ["fi", "n", "e"]
    assert [g.char for g in chain.encode("office")] == ["o", "ffi", "c", "e"]
    assert [g.char for g in chain.encode("if")] == ["i", "f"]


def test_presentation_forms_and_decompositions_are_interchangeable(catalog):
    # ToUnicode maps the glyph to U+FB01; the user types "f" + "i".
    chain = FontChain.build(catalog, _embedded("ﬁ", "n", "e"), None)
    assert [(g.char, g.font_key) for g in chain.encode("fine")] == [("fi", "e99"), ("n", "e99"), ("e", "e99")]
    # ToUnicode maps the glyph to "fi"; the span text (TEXT_PRESERVE_LIGATURES) has U+FB01.
    chain = FontChain.build(catalog, _embedded("fi", "n", "e"), None)
    assert {g.font_key for g in chain.encode("ﬁne")} == {"e99"}


def test_coverage_counts_ligature_glyphs():
    font = _embedded("ffi", "fi", "o", "c", "e")
    assert font.coverage("office") == 1.0
    assert font.coverage("ﬁ") == 1.0
    assert font.coverage("of") == 0.5
