"""Pushing content below a growing text box: moved content must look identical."""

from __future__ import annotations

import pymupdf as fitz
from conftest import current_pdf

from app.pdf import push

TITLE_Y = 100
DY = 40.0


def _model(client, doc_id):
    return client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]


def _items_below(model, top):
    items = []
    for block in model["text"]["blocks"]:
        for line in block["lines"]:
            if top < line["bbox"][1] < 700:
                items.append({"kind": "text", "bbox": line["bbox"]})
    items += [{"kind": "drawing", "bbox": r} for r in model["drawings"] if r[1] > top]
    items += [{"kind": "image", "bbox": i["bbox"], "xref": i["xref"]} for i in model["images"]]
    return items


def _render(pdf: fitz.Document, clip: fitz.Rect) -> fitz.Pixmap:
    return pdf[0].get_pixmap(clip=clip, matrix=fitz.Matrix(2, 2), alpha=False)


def _difference(a: fitz.Pixmap, b: fitz.Pixmap) -> float:
    assert (a.width, a.height) == (b.width, b.height)
    sa, sb = a.samples, b.samples
    return sum(abs(x - y) for x, y in zip(sa, sb)) / len(sa)


def test_page_model_lists_drawing_clusters_including_thin_rules(client, pdoc):
    drawings = _model(client, pdoc["id"])["drawings"]
    assert any(abs(r[1] - 168) < 2 and r[2] - r[0] > 400 for r in drawings), drawings  # the dashed rule
    assert any(abs(r[1] - 180) < 2 for r in drawings)  # the box


def test_clusters_merge_touching_paths():
    rects = [fitz.Rect(10, 10, 50, 10), fitz.Rect(50, 10, 50, 40), fitz.Rect(200, 200, 220, 220)]
    clusters = push.cluster_rects(rects)
    assert len(clusters) == 2


def test_push_moves_everything_below_exactly(client, pdoc):
    before = current_pdf(client, pdoc["id"])
    region = fitz.Rect(60, 120, 560, 250)
    model = _model(client, pdoc["id"])
    title = next(line for b in model["text"]["blocks"] for line in b["lines"] if "title" in line["spans"][0]["text"])
    body = {"page": 0, "bbox": title["bbox"], "text": "Short title that became\na two line heading",
            "align": "left", "width": 400, "push": {"dy": DY, "items": _items_below(model, title["bbox"][3])}}
    response = client.post(f"/api/documents/{pdoc['id']}/text/block", json=body)
    assert response.status_code == 200, response.text
    report = response.json()["data"]["result"]
    assert report["pushed"] >= 5 and report["push_skipped"] == []
    after = current_pdf(client, pdoc["id"])
    moved = _render(after, region + (0, DY, 0, DY))
    assert _difference(_render(before, region), moved) < 2.0  # pixel-identical within antialiasing
    # Text stays real text, in its original fonts and colours.
    spans = [s for b in after[0].get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]]
    para = next(s for s in spans if "Paragraph line two" in s["text"])
    assert abs(para["origin"][1] - (155 + DY)) < 0.6
    assert "LiberationSerif" in para["font"] and para["color"] == 0xB30000
    footer = next(s for s in spans if "Footer" in s["text"])
    assert abs(footer["origin"][1] - 820) < 0.6  # not in the push set: untouched


def test_push_vacated_area_is_clean(client, pdoc):
    model = _model(client, pdoc["id"])
    title = next(line for b in model["text"]["blocks"] for line in b["lines"] if "title" in line["spans"][0]["text"])
    body = {"page": 0, "bbox": title["bbox"], "text": "Short title", "align": "left",
            "push": {"dy": DY, "items": _items_below(model, title["bbox"][3])}}
    assert client.post(f"/api/documents/{pdoc['id']}/text/block", json=body).status_code == 200
    after = current_pdf(client, pdoc["id"])
    strip = _render(after, fitz.Rect(60, 125, 560, 125 + DY - 6))
    assert min(strip.samples) > 235  # nothing left behind


def test_push_can_pull_up(client, pdoc):
    model = _model(client, pdoc["id"])
    title = next(line for b in model["text"]["blocks"] for line in b["lines"] if "title" in line["spans"][0]["text"])
    items = [i for i in _items_below(model, title["bbox"][3]) if i["kind"] == "text" and i["bbox"][1] < 150]
    body = {"page": 0, "bbox": title["bbox"], "text": "Short title", "align": "left", "push": {"dy": -10, "items": items}}
    assert client.post(f"/api/documents/{pdoc['id']}/text/block", json=body).status_code == 200
    spans = [s for b in current_pdf(client, pdoc["id"])[0].get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]]
    assert abs(next(s for s in spans if "line one" in s["text"])["origin"][1] - 130) < 0.6


def test_push_moves_form_fields(client, pdoc):
    doc = current_pdf(client, pdoc["id"])
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "name"
    widget.rect = fitz.Rect(320, 300, 480, 320)
    doc[0].add_widget(widget)
    response = client.post("/api/documents", files={"file": ("f.pdf", doc.tobytes(), "application/pdf")})
    doc_id = response.json()["data"]["id"]
    model = _model(client, doc_id)
    field = model["fields"][0]
    title = next(line for b in model["text"]["blocks"] for line in b["lines"] if "title" in line["spans"][0]["text"])
    body = {"page": 0, "bbox": title["bbox"], "text": "Short title", "align": "left",
            "push": {"dy": DY, "items": [{"kind": "field", "bbox": field["rect"], "xref": field["xref"]}]}}
    assert client.post(f"/api/documents/{doc_id}/text/block", json=body).status_code == 200
    moved = _model(client, doc_id)["fields"][0]["rect"]
    assert abs(moved[1] - (300 + DY)) < 0.6


def test_push_validates_request(client, pdoc):
    model = _model(client, pdoc["id"])
    title = model["text"]["blocks"][0]["lines"][0]
    body = {"page": 0, "bbox": title["bbox"], "text": "x", "align": "left",
            "push": {"dy": 99999, "items": []}}
    assert client.post(f"/api/documents/{pdoc['id']}/text/block", json=body).status_code == 422
