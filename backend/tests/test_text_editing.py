"""Text editing must keep the original embedded font and never corrupt the page."""

from __future__ import annotations

from conftest import current_pdf, page_spans


def _span(client, doc_id, needle, page=0):
    return next(s for s in page_spans(client, doc_id, page) if needle in s["text"])


def _edit(client, doc_id, span, text, **extra):
    body = {"page": 0, "bbox": span["bbox"], "origin": span["origin"], "original_text": span["text"], "text": text}
    body.update(extra)
    return client.post(f"/api/documents/{doc_id}/text/span", json=body)


def test_model_reports_spans_with_fonts(client, doc):
    span = _span(client, doc["id"], "Invoice")
    assert span["font"].startswith("LiberationSans") or "Liberation" in span["font"]
    assert span["bold"] is True
    assert span["size"] == 16
    assert span["face"]


def test_edit_reuses_embedded_font_exactly(client, doc):
    span = _span(client, doc["id"], "Invoice")
    response = _edit(client, doc["id"], span, "Invoice number 54321")
    assert response.status_code == 200, response.text
    report = response.json()["data"]["result"]
    assert report["exact_font"] is True
    assert report["missing_chars"] == []
    pdf = current_pdf(client, doc["id"])
    text = pdf[0].get_text()
    assert "Invoice number 54321" in text
    assert "12345" not in text
    # No new font program embedded: the original subset font object is re-used.
    fonts = {f[3] for f in pdf[0].get_fonts()}
    assert not any("PDFStudio" in name for name in fonts)


def test_edit_with_missing_glyphs_falls_back_per_character(client, doc):
    span = _span(client, doc["id"], "Invoice")
    response = _edit(client, doc["id"], span, "Invoice Ωmega €99")
    assert response.status_code == 200, response.text
    report = response.json()["data"]["result"]
    assert report["exact_font"] is False
    assert len(report["fonts_used"]) >= 2
    assert "Invoice Ωmega €99" in current_pdf(client, doc["id"])[0].get_text()


def test_edit_reflows_rest_of_line(client, doc):
    before = _span(client, doc["id"], "trailing")
    span = _span(client, doc["id"], "Hello world")
    response = _edit(client, doc["id"], span, "Hello there wonderful world from the sample")
    assert response.status_code == 200, response.text
    after = _span(client, doc["id"], "trailing")
    assert after["bbox"][0] > before["bbox"][0] + 20
    assert after["color"] == before["color"]
    assert "trailing words" in current_pdf(client, doc["id"])[0].get_text()


def test_edit_style_changes(client, doc):
    span = _span(client, doc["id"], "Hello world")
    response = _edit(client, doc["id"], span, "Styled text", style={"size": 20, "color": "#0000ff", "underline": True})
    assert response.status_code == 200, response.text
    edited = _span(client, doc["id"], "Styled text")
    assert edited["size"] == 20
    assert edited["color"] == "#0000ff"


def test_edit_and_move(client, doc):
    span = _span(client, doc["id"], "Hello world")
    response = _edit(client, doc["id"], span, span["text"], dx=50, dy=200)
    assert response.status_code == 200, response.text
    moved = _span(client, doc["id"], "Hello world")
    assert abs(moved["origin"][1] - (span["origin"][1] + 200)) < 1
    assert abs(moved["origin"][0] - (span["origin"][0] + 50)) < 1


def test_re_edit_already_edited_text(client, doc):
    span = _span(client, doc["id"], "Invoice")
    assert _edit(client, doc["id"], span, "Receipt number 1").status_code == 200
    again = _span(client, doc["id"], "Receipt")
    assert _edit(client, doc["id"], again, "Receipt number 2").status_code == 200
    text = current_pdf(client, doc["id"])[0].get_text()
    assert "Receipt number 2" in text and "Receipt number 1" not in text


def test_stale_span_is_rejected(client, doc):
    span = _span(client, doc["id"], "Invoice")
    body = {"page": 0, "bbox": [400, 700, 450, 720], "origin": [400, 715], "original_text": "nope", "text": "x"}
    response = client.post(f"/api/documents/{doc['id']}/text/span", json=body)
    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert span  # untouched


def test_block_edit_reflows_paragraph(client, doc):
    span = _span(client, doc["id"], "quick brown")
    model = client.get(f"/api/documents/{doc['id']}/pages/0/model").json()["data"]
    block = next(b for b in model["text"]["blocks"] if any(span["id"] == s["id"] for line in b["lines"] for s in line["spans"]))
    new_text = "A completely rewritten paragraph that is long enough to wrap onto several lines automatically."
    response = client.post(f"/api/documents/{doc['id']}/text/block",
                           json={"page": 0, "bbox": block["bbox"], "text": new_text, "align": "left"})
    assert response.status_code == 200, response.text
    text = current_pdf(client, doc["id"])[0].get_text()
    assert "quick brown" not in text
    assert "rewritten" in text and "automatically." in text
    assert response.json()["data"]["result"]["exact_font"] in (True, False)


def test_block_edit_justify_and_center(client, doc):
    model = client.get(f"/api/documents/{doc['id']}/pages/0/model").json()["data"]
    block = next(b for b in model["text"]["blocks"] if "quick" in str(b))
    for align in ("justify", "center"):
        response = client.post(f"/api/documents/{doc['id']}/text/block",
                               json={"page": 0, "bbox": block["bbox"], "text": "Short centred text", "align": align})
        assert response.status_code == 200, response.text
        block = next(b for b in client.get(f"/api/documents/{doc['id']}/pages/0/model").json()["data"]["text"]["blocks"] if "Short" in str(b))


def test_add_text_with_catalog_font(client, doc):
    response = client.post(f"/api/documents/{doc['id']}/text/add",
                           json={"page": 1, "x": 100, "y": 300, "text": "Brand new text\nSecond line",
                                 "style": {"font": "", "size": 14, "color": "#336699"}})
    assert response.status_code == 200, response.text
    text = current_pdf(client, doc["id"])[1].get_text()
    assert "Brand new text" in text and "Second line" in text


def test_add_text_with_document_font(client, doc):
    fonts = client.get(f"/api/documents/{doc['id']}/fonts").json()["data"]
    assert fonts
    response = client.post(f"/api/documents/{doc['id']}/text/add",
                           json={"page": 0, "x": 100, "y": 500, "text": "Hello",
                                 "style": {"font": f"doc:{fonts[0]['xref']}", "size": 12}})
    assert response.status_code == 200, response.text


def test_replace_all(client, doc):
    response = client.post(f"/api/documents/{doc['id']}/text/replace",
                           json={"query": "text", "replacement": "words"})
    assert response.status_code == 200, response.text
    result = response.json()["data"]["result"]
    assert result["replaced"] >= 1
    assert "Second page words" in current_pdf(client, doc["id"])[1].get_text()


def test_rotated_page_edit(client, doc):
    assert client.post(f"/api/documents/{doc['id']}/pages/rotate", json={"pages": [1], "angle": 90}).status_code == 200
    span = _span(client, doc["id"], "Second page", page=1)
    body = {"page": 1, "bbox": span["bbox"], "origin": span["origin"], "original_text": span["text"], "text": "Rotated edit"}
    response = client.post(f"/api/documents/{doc['id']}/text/span", json=body)
    assert response.status_code == 200, response.text
    edited = _span(client, doc["id"], "Rotated edit", page=1)
    assert abs(edited["origin"][0] - span["origin"][0]) < 1 and abs(edited["origin"][1] - span["origin"][1]) < 1


def test_fallback_glyphs_stay_in_one_editable_run(client, doc):
    span = _span(client, doc["id"], "Invoice")
    assert _edit(client, doc["id"], span, "Invoice Ωmega").status_code == 200
    runs = [s for s in page_spans(client, doc["id"]) if "Ωmega" in s["text"]]
    assert len(runs) == 1
    assert runs[0]["text"] == "Invoice Ωmega"
    assert runs[0]["font"] == span["font"]  # reported with the original font, not the fallback


def _block_of(client, doc_id, needle, page=0):
    model = client.get(f"/api/documents/{doc_id}/pages/{page}/model").json()["data"]
    return next(b for b in model["text"]["blocks"] if any(needle in s["text"] for line in b["lines"] for s in line["spans"]))


def _post_block(client, doc_id, block, text, **extra):
    body = {"page": 0, "bbox": block["bbox"], "text": text, "align": "left"}
    body.update(extra)
    return client.post(f"/api/documents/{doc_id}/text/block", json=body)


def _lines_with(client, doc_id, needle, page=0):
    block = _block_of(client, doc_id, needle, page)
    return [line for line in block["lines"] if any(s["text"].strip() for s in line["spans"])]


def test_block_edit_grows_into_free_space_instead_of_wrapping(client, doc):
    """A short line rewritten longer stays on one line when the box is widened."""
    block = _block_of(client, doc["id"], "Invoice")
    longer = "Invoice number 12345 issued to Alexander Montgomery"
    response = _post_block(client, doc["id"], block, longer, width=420, max_width=460)
    assert response.status_code == 200, response.text
    lines = _lines_with(client, doc["id"], "Montgomery")
    assert len(lines) == 1
    assert "Alexander Montgomery" in "".join(s["text"] for s in lines[0]["spans"])
    # Baseline is unchanged: the text did not move down.
    assert abs(lines[0]["spans"][0]["origin"][1] - 100) < 0.6


def test_block_edit_max_width_tolerates_measurement_differences(client, doc):
    """In auto-width mode the box width may be a hair short; max_width decides wrapping."""
    block = _block_of(client, doc["id"], "Invoice")
    text = "Invoice number 12345 for Alexander"
    response = _post_block(client, doc["id"], block, text, width=50, max_width=500)
    assert response.status_code == 200, response.text
    assert len(_lines_with(client, doc["id"], "Alexander")) == 1


def test_block_edit_wraps_at_narrow_box(client, doc):
    block = _block_of(client, doc["id"], "Invoice")
    response = _post_block(client, doc["id"], block, "Invoice number 12345 for Alexander", width=90)
    assert response.status_code == 200, response.text
    text = current_pdf(client, doc["id"])[0].get_text()
    assert "Alexander" in text
    spans = [s for s in page_spans(client, doc["id"]) if s["text"].strip() and s["origin"][1] < 160]
    baselines = {round(s["origin"][1]) for s in spans if any(w in s["text"] for w in ("Invoice", "number", "12345", "for", "Alexander"))}
    assert len(baselines) >= 2


def test_block_edit_moves_box(client, doc):
    block = _block_of(client, doc["id"], "Invoice")
    response = _post_block(client, doc["id"], block, "Invoice number 12345", dx=40, dy=25, width=300)
    assert response.status_code == 200, response.text
    span = _span(client, doc["id"], "Invoice")
    assert abs(span["origin"][0] - 112) < 1
    assert abs(span["origin"][1] - 125) < 1


def test_block_edit_right_align_in_box(client, doc):
    block = _block_of(client, doc["id"], "Invoice")
    response = _post_block(client, doc["id"], block, "Total", width=300, align="right")
    assert response.status_code == 200, response.text
    span = _span(client, doc["id"], "Total")
    assert abs(span["bbox"][2] - (72 + 300)) < 2


def test_block_edit_rejects_bad_width(client, doc):
    block = _block_of(client, doc["id"], "Invoice")
    response = _post_block(client, doc["id"], block, "x", width=-5)
    assert response.status_code == 422


def test_add_text_auto_width_never_wraps(client, doc):
    """An auto-width new text box sends its measured width; max_width keeps it on one line."""
    body = {"page": 1, "x": 100, "y": 300, "text": "One single line that is wider than its box",
            "style": {"font": "face:" + _any_face(client), "size": 12}, "align": "left",
            "line_height": 1.2, "rotation": 0, "width": 60, "max_width": 20000}
    response = client.post(f"/api/documents/{doc['id']}/text/add", json=body)
    assert response.status_code == 200, response.text
    spans = [s for s in page_spans(client, doc["id"], 1) if "single" in s["text"] or "wider" in s["text"]]
    assert len({round(s["origin"][1]) for s in spans}) == 1


def _any_face(client):
    families = client.get("/api/fonts").json()["data"]["families"]
    return families[0]["faces"][0]["id"]


def _form_doc(client):
    import pymupdf as fitz
    from conftest import find_font

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_font(fontname="F1", fontfile=find_font("LiberationSans-Regular.ttf"))
    page.insert_text((72, 100), "Name:", fontname="F1", fontsize=12)
    page.insert_text((120, 100), "Ravi", fontname="F1", fontsize=12)
    page.insert_text((72, 160), "Item", fontname="F1", fontsize=12)
    page.insert_text((360, 160), "Amount", fontname="F1", fontsize=12)
    response = client.post("/api/documents", files={"file": ("form.pdf", pdf.tobytes(), "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _line(client, doc_id, needle):
    model = client.get(f"/api/documents/{doc_id}/pages/0/model").json()["data"]
    return next(line for b in model["text"]["blocks"] for line in b["lines"] if any(needle in s["text"] for s in line["spans"]))


def test_text_box_edits_only_its_lines_of_a_shared_block(client):
    """Label and value on one baseline may share a block: editing the value keeps the label."""
    form = _form_doc(client)
    value = _line(client, form["id"], "Ravi")
    response = client.post(f"/api/documents/{form['id']}/text/block", json={
        "page": 0, "bbox": value["bbox"], "text": "Ravi Shankar Prasad Srivastava", "align": "left",
        "width": 300, "max_width": 400})
    assert response.status_code == 200, response.text
    label = _line(client, form["id"], "Name:")
    name = _line(client, form["id"], "Srivastava")
    assert abs(label["bbox"][0] - 72) < 1
    assert abs(name["spans"][0]["origin"][0] - 120) < 1.5
    assert abs(name["spans"][0]["origin"][1] - 100) < 0.6
    assert "Name:" not in "".join(s["text"] for s in name["spans"])


def test_text_box_on_a_row_does_not_stack_other_columns(client):
    form = _form_doc(client)
    item = _line(client, form["id"], "Item")
    response = client.post(f"/api/documents/{form['id']}/text/block", json={
        "page": 0, "bbox": item["bbox"], "text": "Item description", "align": "left", "width": 200})
    assert response.status_code == 200, response.text
    amount = _line(client, form["id"], "Amount")
    assert abs(amount["bbox"][0] - 360) < 1
    assert abs(amount["spans"][0]["origin"][1] - 160) < 0.6
