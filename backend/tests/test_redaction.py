"""Redaction must remove what sits under the area beyond page content, and can sanitize the document."""

from __future__ import annotations

import pymupdf as fitz
import pytest

from conftest import current_pdf, find_font

SECRET_AREA = fitz.Rect(60, 80, 300, 120)
FAR_AWAY = fitz.Rect(60, 400, 300, 440)


def make_annotated_pdf(rotation: int = 0) -> bytes:
    """A secret line with a comment, a form field and a link on it, and the same three far away."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="F1", fontfile=find_font("LiberationSans-Regular.ttf"))
    page.insert_text((72, 100), "Salary 91000 confidential", fontname="F1", fontsize=12)
    page.insert_text((72, 420), "Public paragraph", fontname="F1", fontsize=12)
    for area in (SECRET_AREA, FAR_AWAY):
        top = area.y0
        note = page.add_text_annot((area.x0 + 5, top + 5), "contains 91000")
        note.set_info(title="reviewer", content="the salary is 91000")
        note.update()
        page.add_highlight_annot(fitz.Rect(area.x0 + 20, top + 10, area.x0 + 90, top + 30))
        page.add_freetext_annot(fitz.Rect(area.x0 + 100, top + 5, area.x0 + 200, top + 30), "see 91000", fontsize=9)
        widget = fitz.Widget()
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name = f"field_{int(top)}"
        widget.field_value = "91000"
        widget.rect = fitz.Rect(area.x0 + 210, top + 5, area.x0 + 280, top + 25)
        page.add_widget(widget)
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(area.x0 + 5, top + 32, area.x0 + 120, top + 38),
                          "uri": f"https://example.com/?salary=91000&at={int(top)}"})
    doc.set_metadata({"title": "Salary review 91000", "author": "HR", "subject": "payroll"})
    doc.set_xml_metadata("<x:xmpmeta xmlns:x='adobe:ns:meta/'><secret>91000</secret></x:xmpmeta>")
    doc.embfile_add("payslip.txt", b"salary 91000")
    doc.set_toc([[1, "Salary 91000", 1]])
    page.set_rotation(rotation)
    return doc.tobytes(garbage=1, deflate=True)


@pytest.fixture()
def annotated(client) -> dict:
    response = client.post("/api/documents", files={"file": ("a.pdf", make_annotated_pdf(), "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def redact(client, doc, mode="redact", **extra):
    body = {"page": 0, "rects": [list(SECRET_AREA)], "mode": mode, **extra}
    return client.post(f"/api/documents/{doc['id']}/redact", json=body)


def contents(client, doc_id: str) -> dict:
    page = current_pdf(client, doc_id)[0]
    return {
        "annots": sorted((a.type[1], round(a.rect.y0)) for a in page.annots()),
        "widgets": sorted(w.field_name for w in page.widgets()),
        "links": sorted(link["uri"] for link in page.get_links()),
    }


def test_fixture_has_everything_in_both_places(client, annotated):
    state = contents(client, annotated["id"])
    assert len(state["annots"]) == 6 and len(state["widgets"]) == 2 and len(state["links"]) == 2


def test_redaction_removes_annotations_fields_and_links_under_the_area(client, annotated):
    response = redact(client, annotated)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["result"] == {"annotations": 3, "fields": 1, "links": 1, "sanitized": False}
    state = contents(client, annotated["id"])
    assert all(y >= 400 for _kind, y in state["annots"]) and len(state["annots"]) == 3
    assert state["widgets"] == ["field_400"]
    assert [uri for uri in state["links"] if "at=80" in uri] == []
    assert len(state["links"]) == 1
    pdf = current_pdf(client, annotated["id"])
    assert "91000" not in pdf[0].get_text().split("Public")[0]
    assert "Public paragraph" in pdf[0].get_text()


def test_nothing_under_the_area_is_left_in_the_file(client, annotated):
    redact(client, annotated)
    from app import deps

    pdf = fitz.open(stream=deps.store().current_bytes(annotated["id"]))
    objects = " ".join(pdf.xref_object(x) for x in range(1, pdf.xref_length()) if not pdf.xref_is_stream(x))
    assert "at=80" not in objects and "field_80" not in objects
    assert objects.count("the salary is 91000") == 1  # only the note far away from the area is left


def test_partially_covered_annotations_are_removed_too(client, annotated):
    """Clipping a comment or field is not possible, so anything that overlaps the area goes."""
    area = [list(fitz.Rect(SECRET_AREA.x0 + 275, SECRET_AREA.y0 + 20, SECRET_AREA.x0 + 400, SECRET_AREA.y0 + 60))]
    response = client.post(f"/api/documents/{annotated['id']}/redact", json={"page": 0, "rects": area, "mode": "redact"})
    assert response.json()["data"]["result"]["fields"] == 1  # the field only overlaps the right edge


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_links_fields_and_comments_are_found_on_rotated_pages(client, rotation):
    """Link rectangles are reported in display space, comments and fields in page space."""
    pdf = make_annotated_pdf(rotation)
    created = client.post("/api/documents", files={"file": ("r.pdf", pdf, "application/pdf")}).json()["data"]
    page = current_pdf(client, created["id"])[0]
    display_area = tuple(fitz.Rect(SECRET_AREA) * page.rotation_matrix)
    response = client.post(f"/api/documents/{created['id']}/redact",
                           json={"page": 0, "rects": [display_area], "mode": "redact"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["result"] == {"annotations": 3, "fields": 1, "links": 1, "sanitized": False}
    state = contents(client, created["id"])
    assert state["widgets"] == ["field_400"] and len(state["links"]) == 1 and len(state["annots"]) == 3


@pytest.mark.parametrize("mode", ["whiteout", "text"])
def test_cosmetic_modes_keep_comments_and_fields(client, annotated, mode):
    response = redact(client, annotated, mode=mode)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["result"] == {"annotations": 0, "fields": 0, "links": 0, "sanitized": False}
    state = contents(client, annotated["id"])
    assert ("Text", 85) in state["annots"] and ("Highlight", 89) in state["annots"]
    assert state["widgets"] == ["field_400", "field_80"]


def test_redact_search_clears_annotations_under_each_match(client, annotated):
    response = client.post(f"/api/documents/{annotated['id']}/redact/search", json={"query": "confidential"})
    assert response.status_code == 200, response.text
    result = response.json()["data"]["result"]
    assert result["redacted"] == 1 and result["annotations"] >= 1
    assert "confidential" not in current_pdf(client, annotated["id"])[0].get_text()


def test_metadata_is_kept_unless_sanitizing_is_requested(client, annotated):
    redact(client, annotated)
    pdf = current_pdf(client, annotated["id"])
    assert pdf.metadata["title"] == "Salary review 91000"
    assert pdf.embfile_names() == ["payslip.txt"]


def test_sanitize_removes_metadata_xmp_and_attachments(client, annotated):
    response = redact(client, annotated, sanitize=True)
    assert response.status_code == 200, response.text
    pdf = current_pdf(client, annotated["id"])
    assert not any((pdf.metadata or {}).get(k) for k in ("title", "author", "subject", "keywords"))
    assert pdf.embfile_names() == []
    assert not pdf.get_xml_metadata()
    # Comments away from the redacted area are not metadata and stay.
    assert len(contents(client, annotated["id"])["annots"]) == 3


def test_sanitize_also_works_with_redact_search(client, annotated):
    client.post(f"/api/documents/{annotated['id']}/redact/search", json={"query": "confidential", "sanitize": True})
    pdf = current_pdf(client, annotated["id"])
    assert pdf.embfile_names() == [] and not pdf.metadata["title"]


def test_sanitize_removes_bookmarks_but_a_plain_redaction_keeps_them(client, annotated):
    redact(client, annotated)
    assert current_pdf(client, annotated["id"]).get_toc() == [[1, "Salary 91000", 1]]
    redact(client, annotated, sanitize=True)
    assert current_pdf(client, annotated["id"]).get_toc() == []


# ------------------------------------------------------------------ pending ("marked") redactions
def make_marked_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "SECRET alpha", fontsize=14)
    page.insert_text((72, 200), "KEEP beta", fontsize=14)
    marked = page.add_redact_annot(fitz.Rect(70, 185, 200, 210), text="OVERLAY", fill=(1, 0, 0), text_color=(0, 0, 1))
    marked.set_info(title="reviewer", content="mark")
    marked.update()
    return doc.tobytes()


def pending(page: fitz.Page) -> list[dict]:
    doc = page.parent
    return [{"info": a.info, "rect": tuple(a.rect), "object": doc.xref_object(a.xref, compressed=True)}
            for a in page.annots(types=[fitz.PDF_ANNOT_REDACT])]


def test_redacting_elsewhere_keeps_marked_redactions_exactly(client):
    created = client.post("/api/documents", files={"file": ("m.pdf", make_marked_pdf(), "application/pdf")}).json()["data"]
    before = pending(current_pdf(client, created["id"])[0])
    assert len(before) == 1
    response = client.post(f"/api/documents/{created['id']}/redact",
                           json={"page": 0, "rects": [[60, 80, 200, 110]], "mode": "redact"})
    assert response.status_code == 200, response.text
    after_pdf = current_pdf(client, created["id"])[0]
    text = after_pdf.get_text()
    assert "SECRET" not in text and "KEEP beta" in text, "the marked area must not have been applied"
    after = pending(after_pdf)
    assert [(p["info"], p["rect"]) for p in after] == [(p["info"], p["rect"]) for p in before]
    assert "OverlayText(OVERLAY)" in after[0]["object"] and "/IC[1 0 0]" in after[0]["object"]


def test_forced_ocr_cleanup_does_not_apply_marked_redactions():
    from app.pdf import ocr

    doc = fitz.open(stream=make_marked_pdf())
    ocr.remove_invisible_text(doc[0])
    assert "KEEP beta" in doc[0].get_text()
    assert len(pending(doc[0])) == 1
