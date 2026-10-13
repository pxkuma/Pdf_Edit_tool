"""Styles applied by the editor must be detected again and be switchable off.

Toggling a style on text that already has it (e.g. strikethrough) must remove
it, not draw it a second time.
"""

from __future__ import annotations

import pytest
from conftest import current_pdf, page_spans


def _span(client, doc_id, needle):
    return next(s for s in page_spans(client, doc_id) if needle in s["text"])


def _edit(client, doc_id, needle, text=None, **style):
    span = _span(client, doc_id, needle)
    body = {"page": 0, "bbox": span["bbox"], "origin": span["origin"], "original_text": span["text"],
            "text": span["text"] if text is None else text, "style": {"font": "original", **style}}
    response = client.post(f"/api/documents/{doc_id}/text/span", json=body)
    assert response.status_code == 200, response.text
    return response


def _rules(client, doc_id):
    """Horizontal line segments drawn on page 0 (decorations)."""
    page = current_pdf(client, doc_id)[0]
    return [d["rect"] for d in page.get_drawings() if d["rect"].height < 3 and d["rect"].width > 5]


@pytest.mark.parametrize("kind", ["strike", "underline"])
def test_decoration_is_detected_and_toggles_off(client, doc, kind):
    _edit(client, doc["id"], "Hello world", **{kind: True})
    span = _span(client, doc["id"], "Hello world")
    assert span[kind] is True
    assert len(_rules(client, doc["id"])) == 1
    _edit(client, doc["id"], "Hello world", **{kind: False})
    assert _span(client, doc["id"], "Hello world")[kind] is False
    assert _rules(client, doc["id"]) == []


def test_decoration_follows_new_text_without_duplicates(client, doc):
    _edit(client, doc["id"], "Hello world", strike=True)
    short = _rules(client, doc["id"])[0]
    _edit(client, doc["id"], "Hello world", "Hello world from a much longer sentence", strike=True)
    rules = _rules(client, doc["id"])
    assert len(rules) == 1
    assert rules[0].width > short.width + 50


def test_unrelated_edit_keeps_existing_decoration(client, doc):
    _edit(client, doc["id"], "Hello world", underline=True)
    span = _span(client, doc["id"], "Hello world")
    _edit(client, doc["id"], "Hello world", "Hello world!", underline=span["underline"])
    assert len(_rules(client, doc["id"])) == 1
    assert _span(client, doc["id"], "Hello world")["underline"] is True


def test_shifted_followers_keep_their_decoration(client, doc):
    _edit(client, doc["id"], "trailing", underline=True)
    _edit(client, doc["id"], "Hello world", "Hello there wonderful world from the sample")
    follower = _span(client, doc["id"], "trailing")
    assert follower["underline"] is True
    rules = _rules(client, doc["id"])
    assert len(rules) == 1
    assert abs(rules[0].x0 - follower["bbox"][0]) < 2  # the line moved with its text


def test_synthetic_bold_is_detected_and_toggles_off(client, doc):
    assert _span(client, doc["id"], "Hello world")["bold"] is False
    _edit(client, doc["id"], "Hello world", bold=True)
    span = _span(client, doc["id"], "Hello world")
    assert span["bold"] is True
    _edit(client, doc["id"], "Hello world", bold=False)
    span = _span(client, doc["id"], "Hello world")
    assert span["bold"] is False and span["renderMode"] == 0


def test_synthetic_italic_is_detected_and_toggles_off(client, doc):
    _edit(client, doc["id"], "Hello world", italic=True)
    span = _span(client, doc["id"], "Hello world")
    assert span["italic"] is True
    _edit(client, doc["id"], "Hello world", italic=False)
    span = _span(client, doc["id"], "Hello world")
    assert span["italic"] is False and abs(span["skew"]) < 0.01


def test_real_bold_font_can_be_made_regular(client, doc):
    assert _span(client, doc["id"], "Invoice")["bold"] is True
    _edit(client, doc["id"], "Invoice", bold=False)
    span = _span(client, doc["id"], "Invoice")
    assert span["bold"] is False
    assert "bold" not in span["font"].lower()


def test_bold_twice_does_not_thicken(client, doc):
    _edit(client, doc["id"], "Hello world", bold=True)
    first = _span(client, doc["id"], "Hello world")
    _edit(client, doc["id"], "Hello world", "Hello world again")  # bold unchanged (not sent)
    second = _span(client, doc["id"], "Hello world")
    assert second["bold"] is True and second["renderMode"] == first["renderMode"]


def test_opacity_can_be_restored_to_full(client, doc):
    _edit(client, doc["id"], "Hello world", opacity=0.5)
    assert abs(_span(client, doc["id"], "Hello world")["opacity"] - 0.5) < 0.02
    _edit(client, doc["id"], "Hello world", opacity=1.0)
    assert _span(client, doc["id"], "Hello world")["opacity"] > 0.99


def test_edited_text_shows_a_readable_font_name(client, doc):
    _edit(client, doc["id"], "Hello world", "Hello wörld Ω")  # forces a fallback font for Ω
    _edit(client, doc["id"], "Hello", bold=True, font="face:" + _face_id(client, "Liberation Serif"))
    span = _span(client, doc["id"], "Hello")
    assert not span["font"].startswith("PSF"), span["font"]
    assert "Liberation Serif" in span["font"]


def _face_id(client, family):
    families = client.get("/api/fonts").json()["data"]["families"]
    return next(f for f in families if f["family"] == family)["faces"][0]["id"]
