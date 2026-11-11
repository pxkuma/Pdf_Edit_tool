"""Installed-font catalog: family filtering, substitutes and fallbacks (audit C15, C16, C17)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont
from test_font_library import make_font

from app.pdf.fonts import FontCatalog
from app.pdf.textwriter import FontChain

FACES = [
    ("Liberation Sans", "Regular", 400), ("Liberation Sans", "Bold", 700),
    ("Liberation Sans Narrow", "Regular", 400),
    ("Liberation Serif", "Regular", 400),
    ("Liberation Mono", "Regular", 400),
    ("Roboto", "Regular", 400), ("Roboto", "Bold", 700),
    ("Roboto Condensed", "Regular", 400),
    ("Playfair Display", "Regular", 400),
    ("Noto Sans", "Regular", 400), ("Noto Sans", "Bold", 700),
    ("Noto Serif", "Regular", 400), ("Noto Serif", "Bold", 700),
    ("Noto Sans Symbols", "Regular", 400), ("Noto Sans Symbols", "Bold", 700),
]


def _write(directory: Path, family: str, style: str, weight: int) -> None:
    font = TTFont(io.BytesIO(make_font(family, style, weight)))
    if "Mono" in family:
        font["post"].isFixedPitch = 1
    font.save(str(directory / f"{family.replace(' ', '')}-{style.replace(' ', '')}.ttf"))


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> FontCatalog:
    directory = tmp_path_factory.mktemp("catalog-fonts")
    for family, style, weight in FACES:
        _write(directory, family, style, weight)
    return FontCatalog([directory], directory / "cache.json")


def test_display_and_condensed_families_are_listed(catalog):
    families = catalog.families()
    assert "Playfair Display" in families
    assert "Roboto Condensed" in families


@pytest.mark.parametrize(("pdf_name", "family"), [
    ("RobotoMono-Regular", "Liberation Mono"),  # not proportional Roboto
    ("NotoSansMono-Bold", "Liberation Mono"),
    ("ArialNarrow", "Liberation Sans Narrow"),  # not wide Liberation Sans
    ("Arial-BoldMT", "Liberation Sans"),
    ("Roboto-Bold", "Roboto"),
    ("TimesNewRomanPSMT", "Liberation Serif"),
])
def test_substitute_keeps_mono_and_narrow_fonts(catalog, pdf_name, family):
    face = catalog.substitute(pdf_name, False, False, False, False)
    assert face is not None and face.family == family


def test_fallbacks_follow_weight_and_serif_class(catalog):
    regular = catalog.coverage_fallbacks()
    assert (regular[0].family, regular[0].bold) == ("Noto Sans", False)
    bold = catalog.coverage_fallbacks(bold=True)
    assert (bold[0].family, bold[0].bold) == ("Noto Sans", True)
    assert any(f.family == "Noto Sans Symbols" and f.bold for f in bold)
    serif = catalog.coverage_fallbacks(serif=True)
    assert serif[0].family == "Noto Serif"


def test_chain_fallbacks_match_the_primary_face(catalog):
    primary = catalog.pick_variant("Liberation Sans", True, False)
    chain = FontChain.build(catalog, None, primary)
    assert [e.face.bold for e in chain.faces[:2]] == [True, True]
    assert chain.faces[1].face.family == "Noto Sans"


def test_fallbacks_are_cached_until_fonts_change(catalog, tmp_path):
    assert catalog.coverage_fallbacks() is catalog.coverage_fallbacks()
    before = catalog.coverage_fallbacks()
    _write(tmp_path, "Noto Sans Extra", "Regular", 400)
    catalog.add_user_font(tmp_path / "NotoSansExtra-Regular.ttf")
    after = catalog.coverage_fallbacks()
    assert after is not before
    assert any(f.family == "Noto Sans Extra" for f in after)
