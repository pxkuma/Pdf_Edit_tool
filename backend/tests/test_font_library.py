"""Downloading the free font a PDF uses (Google Fonts), fully offline via a fake fetcher."""

from __future__ import annotations

import io
from pathlib import Path
from typing import ClassVar

import pytest
from conftest import find_font
from fontTools.ttLib import TTFont

from app.pdf import fontlib
from app.pdf.fonts import FontCatalog


def make_font(family: str, style: str, weight: int, italic: bool = False) -> bytes:
    """A real TrueType font renamed to ``family``/``style``."""
    font = TTFont(find_font("LiberationSans-Regular.ttf"))
    full = f"{family} {style}".replace(" Regular", "")
    for record in font["name"].names:
        value = {1: family if style in ("Regular", "Bold", "Italic", "Bold Italic") else f"{family} {style}",
                 2: style if style in ("Regular", "Bold", "Italic", "Bold Italic") else "Regular",
                 4: full, 6: full.replace(" ", "-"), 16: family, 17: style}.get(record.nameID)
        if value is not None:
            record.string = value
    font["name"].setName(family, 16, 3, 1, 0x409)
    font["name"].setName(style, 17, 3, 1, 0x409)
    font["OS/2"].usWeightClass = weight
    font["OS/2"].fsSelection = (font["OS/2"].fsSelection & ~0x61) | (0x01 if italic else 0) | (0x20 if weight >= 700 else 0)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


class FakeGoogle:
    """Serves the Google Fonts CSS API and font files for a few families."""

    STYLES: ClassVar[dict[str, list[tuple[int, bool]]]] = {"Montserrat": [(400, False), (600, False), (700, False), (400, True), (600, True), (700, True)]}

    def __init__(self, offline: bool = False) -> None:
        self.offline = offline
        self.requests: list[str] = []

    def __call__(self, url: str, limit: int) -> bytes:
        self.requests.append(url)
        if self.offline:
            raise fontlib.FontLibraryOffline("offline")
        if url.startswith(fontlib.GOOGLE_CSS):
            return self._css(url).encode()
        family, weight, italic = url.rsplit("/", 1)[1].removesuffix(".ttf").split("_")
        style = {400: "Regular", 600: "SemiBold", 700: "Bold"}[int(weight)]
        if italic == "i":
            style = "Italic" if style == "Regular" else f"{style} Italic"
        return make_font(family.replace("+", " "), style, int(weight), italic == "i")

    def _css(self, url: str) -> str:
        query = url.split("family=", 1)[1]
        family, _, spec = query.partition(":")
        family = family.replace("+", " ").replace("%20", " ")
        styles = self.STYLES.get(family)
        if styles is None:
            raise fontlib.FontNotFound(family)
        wanted = [(400, False)]
        if spec:
            wanted = [(int(w), i == "1") for i, w in (pair.split(",") for pair in spec.split("@", 1)[1].split(";"))]
        if any(style not in styles for style in wanted):
            raise fontlib.FontNotFound(family)
        blocks = []
        for weight, italic in wanted:
            src = f"https://fonts.gstatic.com/s/{family.replace(' ', '+')}_{weight}_{'i' if italic else 'n'}.ttf"
            blocks.append(f"@font-face {{\n  font-family: '{family}';\n  font-style: {'italic' if italic else 'normal'};\n"
                          f"  font-weight: {weight};\n  src: url({src}) format('truetype');\n}}")
        return "\n".join(blocks)


@pytest.fixture()
def catalog(tmp_path) -> FontCatalog:
    return FontCatalog([Path(find_font("LiberationSans-Regular.ttf")).parent], tmp_path / "cache.json")


# ------------------------------------------------------------------ names
@pytest.mark.parametrize("pdf_name, family", [
    ("ABCDEF+Montserrat-SemiBold", "Montserrat"),
    ("OpenSans-BoldItalic", "Open Sans"),
    ("PlayfairDisplay-Regular", "Playfair Display"),
    ("MontserratSemiBold", "Montserrat"),
    ("Roboto", "Roboto"),
    ("SourceSans3-Regular", "Source Sans 3"),
    ("Lato,Bold", "Lato"),
    ("OCYBIG+Montserrat SemiBold", "Montserrat"),
    ("Open Sans Bold Italic", "Open Sans"),
])
def test_family_from_pdf_name(pdf_name, family):
    assert fontlib.family_candidates(pdf_name)[0] == family


@pytest.mark.parametrize("pdf_name, weight, italic", [
    ("Montserrat-SemiBoldItalic", 600, True),
    ("Arial-BoldMT", 700, False),
    ("Lato-Light", 300, False),
    ("Roboto", 400, False),
    ("Poppins-ExtraBold", 800, False),
])
def test_style_from_pdf_name(pdf_name, weight, italic):
    assert fontlib.style_of(pdf_name) == (weight, italic)


@pytest.mark.parametrize("pdf_name", ["ArialMT", "Calibri-Bold", "TimesNewRomanPS-BoldMT", "Helvetica", "SegoeUI"])
def test_commercial_fonts_are_not_downloaded(pdf_name):
    assert fontlib.is_commercial(pdf_name)


def test_free_font_is_not_commercial():
    assert not fontlib.is_commercial("Montserrat-Regular")


# ------------------------------------------------------------------ lookup / download
def test_lookup_finds_downloadable_family(catalog):
    result = fontlib.lookup(catalog, "ABCDEF+Montserrat-SemiBold", fetch=FakeGoogle())
    assert result.status == "downloadable"
    assert result.family == "Montserrat"


def test_lookup_unknown_and_commercial(catalog):
    assert fontlib.lookup(catalog, "Zzyzx-Regular", fetch=FakeGoogle()).status == "unknown"
    commercial = fontlib.lookup(catalog, "Calibri", fetch=FakeGoogle())
    assert commercial.status == "commercial"
    assert commercial.substitute


def test_lookup_offline(catalog):
    assert fontlib.lookup(catalog, "Montserrat-Regular", fetch=FakeGoogle(offline=True)).status == "offline"


def test_lookup_installed(catalog):
    assert fontlib.lookup(catalog, "LiberationSans-Bold", fetch=FakeGoogle()).status == "installed"


def test_download_installs_the_used_weight_and_basics(catalog, tmp_path):
    fake = FakeGoogle()
    faces = fontlib.download(catalog, "ABCDEF+Montserrat-SemiBold", tmp_path / "fonts", fetch=fake)
    styles = {face.style for face in faces}
    assert {"SemiBold", "Regular", "Bold", "Italic"} <= styles
    assert all(face.family == "Montserrat" for face in faces)
    assert all("fonts.gstatic.com" in url or url.startswith(fontlib.GOOGLE_CSS) for url in fake.requests)
    # From now on the PDF's font resolves to the real family, in the right weight.
    face = catalog.substitute("Montserrat-SemiBold", True, False, False, False)
    assert face.family == "Montserrat" and face.style == "SemiBold"
    assert catalog.exact_family("ABCDEF+Montserrat-SemiBold") == "Montserrat"
    assert fontlib.lookup(catalog, "Montserrat-SemiBold", fetch=fake).status == "installed"


def test_download_rejects_foreign_hosts(catalog, tmp_path):
    def evil(url, limit):
        if url.startswith(fontlib.GOOGLE_CSS):
            return b"@font-face { font-style: normal; font-weight: 400; src: url(https://evil.example/x.ttf); }"
        raise AssertionError("must not fetch from a foreign host")

    with pytest.raises(fontlib.FontLibraryError):
        fontlib.download(catalog, "Montserrat-Regular", tmp_path / "fonts", fetch=evil)


def test_download_rejects_non_font_data(catalog, tmp_path):
    def junk(url, limit):
        if url.startswith(fontlib.GOOGLE_CSS):
            return FakeGoogle()(url, limit)
        return b"<html>not a font</html>"

    with pytest.raises(fontlib.FontLibraryError):
        fontlib.download(catalog, "Montserrat-Regular", tmp_path / "fonts", fetch=junk)


# ------------------------------------------------------------------ API
def test_font_lookup_and_download_api(client, monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(fontlib, "fetch_url", fake)
    fontlib.clear_cache()
    lookup = client.get("/api/fonts/lookup", params={"name": "ABCDEF+Montserrat-SemiBold"}).json()["data"]
    assert lookup["status"] == "downloadable" and lookup["family"] == "Montserrat"
    response = client.post("/api/fonts/download", json={"name": "ABCDEF+Montserrat-SemiBold"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["family"] == "Montserrat"
    assert data["face"]  # best face for the PDF font, for previews
    families = {f["family"] for f in client.get("/api/fonts").json()["data"]["families"]}
    assert "Montserrat" in families


def test_font_api_rejects_bad_names(client):
    assert client.get("/api/fonts/lookup", params={"name": "x" * 300}).status_code == 422
    assert client.post("/api/fonts/download", json={"name": ""}).status_code == 422


def test_page_model_flags_installed_fonts(client, doc):
    model = client.get(f"/api/documents/{doc['id']}/pages/0/model").json()["data"]
    spans = [s for b in model["text"]["blocks"] for line in b["lines"] for s in line["spans"]]
    assert all("installed" in s for s in spans)
    assert any(s["installed"] for s in spans)  # sample uses Liberation fonts, which are installed
