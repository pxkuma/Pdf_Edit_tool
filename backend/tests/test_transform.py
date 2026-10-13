"""Moving and resizing page objects directly (Canva-style), exactly."""

from __future__ import annotations

import pymupdf as fitz
from conftest import current_pdf
from test_push import _difference, _model, _render


def _transform(client, doc_id, items, src, dst):
    body = {"page": 0, "items": items, "from_rect": src, "to_rect": dst}
    return client.post(f"/api/documents/{doc_id}/objects/transform", json=body)


def _line(model, needle):
    return next(line for b in model["text"]["blocks"] for line in b["lines"] if needle in line["spans"][0]["text"])


def test_move_text_box_anywhere_exactly(client, pdoc):
    before = current_pdf(client, pdoc["id"])
    model = _model(client, pdoc["id"])
    lines = [_line(model, "Paragraph line one"), _line(model, "Paragraph line two")]
    src = [min(l["bbox"][0] for l in lines), lines[0]["bbox"][1], max(l["bbox"][2] for l in lines), lines[1]["bbox"][3]]
    dst = [src[0] + 250, src[1] + 400, src[2] + 250, src[3] + 400]  # far right, near the bottom: no limits
    response = _transform(client, pdoc["id"], [{"kind": "text", "bbox": l["bbox"]} for l in lines], src, dst)
    assert response.status_code == 200, response.text
    after = current_pdf(client, pdoc["id"])
    region = fitz.Rect(src) + (-2, -2, 2, 2)
    assert _difference(_render(before, region), _render(after, region + (250, 400, 250, 400))) < 2.0
    spans = [s for b in after[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    red = next(s for s in spans if "line two" in s["text"])
    assert red["color"] == 0xB30000 and "LiberationSerif" in red["font"]  # mixed styles kept exactly


def test_resize_image_and_drawing(client, pdoc):
    model = _model(client, pdoc["id"])
    image = model["images"][0]
    src = image["bbox"]
    dst = [src[0] - 20, src[1], src[2] + 60, src[3] + 40]
    response = _transform(client, pdoc["id"], [{"kind": "image", "bbox": src, "xref": image["xref"]}], src, dst)
    assert response.status_code == 200, response.text
    moved = _model(client, pdoc["id"])["images"][0]["bbox"]
    assert all(abs(a - b) < 0.6 for a, b in zip(moved, dst))
    box = next(r for r in _model(client, pdoc["id"])["drawings"] if abs(r[1] - 180) < 2)
    big = [box[0], box[1], box[2] + 100, box[3] + 50]
    response = _transform(client, pdoc["id"], [{"kind": "drawing", "bbox": box}], box, big)
    assert response.status_code == 200, response.text
    assert any(abs(r[2] - big[2]) < 1.5 and abs(r[3] - big[3]) < 1.5 for r in _model(client, pdoc["id"])["drawings"])


def test_moved_text_takes_its_underline_along(client, pdoc):
    model = _model(client, pdoc["id"])
    line = _line(model, "Paragraph line two")
    span = line["spans"][0]
    body = {"page": 0, "bbox": span["bbox"], "origin": span["origin"], "original_text": span["text"],
            "text": span["text"], "style": {"font": "original", "underline": True}}
    assert client.post(f"/api/documents/{pdoc['id']}/text/span", json=body).status_code == 200
    line = _line(_model(client, pdoc["id"]), "Paragraph line two")
    src = line["bbox"]
    dst = [src[0] + 100, src[1] + 300, src[2] + 100, src[3] + 300]
    assert _transform(client, pdoc["id"], [{"kind": "text", "bbox": src}], src, dst).status_code == 200
    moved = _line(_model(client, pdoc["id"]), "Paragraph line two")
    assert moved["spans"][0]["underline"] is True
    rules = [d["rect"] for d in current_pdf(client, pdoc["id"])[0].get_drawings() if d["rect"].height < 3 and d["rect"].width < 300]
    assert all(r.y0 > 300 for r in rules)  # nothing left behind


def test_transform_rejects_empty(client, pdoc):
    response = _transform(client, pdoc["id"], [], [0, 0, 10, 10], [5, 5, 15, 15])
    assert response.status_code in (400, 422)


def test_delete_objects(client, pdoc):
    model = _model(client, pdoc["id"])
    line = _line(model, "Paragraph line one")
    image = model["images"][0]
    box = next(r for r in model["drawings"] if abs(r[1] - 180) < 2)
    items = [{"kind": "text", "bbox": line["bbox"]}, {"kind": "image", "bbox": image["bbox"], "xref": image["xref"]},
             {"kind": "drawing", "bbox": box}]
    response = client.post(f"/api/documents/{pdoc['id']}/objects/delete", json={"page": 0, "items": items})
    assert response.status_code == 200, response.text
    after = _model(client, pdoc["id"])
    text = " ".join(s["text"] for b in after["text"]["blocks"] for l in b["lines"] for s in l["spans"])
    assert "line one" not in text and "line two" in text and "Inside a box" in text
    assert after["images"] == []
    assert not any(abs(r[1] - 180) < 2 for r in after["drawings"])
