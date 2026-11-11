"""XFDF export and import: standard output, Acrobat-style input, round trips and hostile files."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

import pymupdf as fitz
import pytest

from conftest import current_pdf
from test_comments import add, base, by_xref, listing, reply, set_status

NS = "{http://ns.adobe.com/xfdf/}"
FAKE_PASSWD = "root:x:0:0:SECRET-CANARY:/root:/bin/sh"


def export(client, doc: dict) -> bytes:
    response = client.get(f"{base(doc)}/comments/xfdf")
    assert response.status_code == 200, response.text
    return response.content


def import_xfdf(client, doc: dict, data: bytes | str, name: str = "comments.xfdf"):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return client.post(f"{base(doc)}/comments/xfdf", files={"file": (name, data, "application/vnd.adobe.xfdf")})


def report(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()["data"]["result"]


def blank_copy(client, sample_pdf: bytes) -> dict:
    response = client.post("/api/documents", files={"file": ("copy.pdf", sample_pdf, "application/pdf")})
    return response.json()["data"]


def populate(client, doc: dict) -> dict[str, int]:
    """One of every kind, a thread and a status: the document the round trip tests start from."""
    words = client.get(f"{base(doc)}/pages/0/model").json()["data"]["text"]["words"]
    word = next(w for w in words if w["text"] == "Hello")
    ids = {"note": add(client, doc, text="Look here & <check> \"this\"", author="Alice")}
    ids["highlight"] = add(client, doc, kind="highlight", rects=[word["bbox"]], text="Nice word", author="Bob")
    ids["underline"] = add(client, doc, kind="underline", rects=[word["bbox"]], author="Bob")
    ids["textbox"] = add(client, doc, kind="textbox", rect=[50, 300, 250, 350], text="Free text", author="Carol", point=None)
    style = {"color": "#2563eb", "fill": "#eeeeff", "opacity": 1, "width": 2, "dashed": False, "contents": "", "author": "Zed"}
    for kind in ("rect", "ellipse"):
        client.post(f"{base(doc)}/annotations", json={"page": 0, "kind": kind, "start": [300, 300], "end": [380, 360], "style": style})
    client.post(f"{base(doc)}/annotations", json={"page": 0, "kind": "arrow", "start": [300, 400], "end": [380, 460], "style": style})
    client.post(f"{base(doc)}/annotations", json={"page": 0, "kind": "ink", "paths": [[[10, 500], [50, 520], [90, 500]]], "style": style})
    first = reply(client, doc, ids["note"], "I agree\nwith two lines", "Bob")
    reply(client, doc, first, "Me too", "Alice")
    set_status(client, doc, ids["note"], status="accepted", author="Carol")
    set_status(client, doc, ids["highlight"], checked=True, author="Bob")
    ids["on_page_two"] = add(client, doc, page=1, point=[60, 60], text="Second page", author="Dan")
    return ids


def comparable(data: dict) -> list:
    """What a comment *is*: everything except the ids that are different in every document."""
    keep = ("type", "author", "subject", "contents", "created", "modified", "color", "status", "statusBy",
            "checked", "quote", "page")

    def one(comment: dict) -> dict:
        shown = {key: comment[key] for key in keep}
        shown["rect"] = [round(v, 1) for v in comment["rect"]]
        shown["replies"] = [one(r) for r in comment.get("replies", [])]
        return shown

    return [one(c) for c in data["comments"]]


# ------------------------------------------------------------------ export
def test_export_is_standard_xfdf(client, doc):
    populate(client, doc)
    root = ET.fromstring(export(client, doc))
    assert root.tag == f"{NS}xfdf"
    assert root.find(f"{NS}f").get("href") == "sample.pdf"
    nodes = root.find(f"{NS}annots")
    tags = [node.tag.removeprefix(NS) for node in nodes]
    assert {"text", "highlight", "underline", "freetext", "square", "circle", "line", "ink"} <= set(tags)
    note = next(n for n in nodes if n.get("title") == "Alice" and n.get("inreplyto") is None and n.tag == f"{NS}text")
    assert note.find(f"{NS}contents").text == "Look here & <check> \"this\""
    assert note.get("page") == "0" and note.get("subject") == "Sticky Note"
    assert note.get("date", "").startswith("D:") and note.get("creationdate", "").startswith("D:")
    assert "print" in note.get("flags", "")
    # XFDF rectangles are PDF user space: y counts up from the bottom edge (a note at y=200 on a 842 pt page).
    left, bottom, right, top = (float(v) for v in note.get("rect").split(","))
    assert (left, round(top), round(bottom)) == (100, 642, 626)


def test_export_lists_threads_and_states_after_their_comment(client, doc):
    ids = populate(client, doc)
    nodes = list(ET.fromstring(export(client, doc)).find(f"{NS}annots"))
    names = {n.get("name"): n for n in nodes}
    position = {id(n): i for i, n in enumerate(nodes)}
    for child in (n for n in nodes if n.get("inreplyto")):
        assert position[id(names[child.get("inreplyto")])] < position[id(child)]
        assert child.get("replyType") == "R"
    note = by_xref(listing(client, doc), ids["note"])
    answers = [n for n in nodes if n.get("inreplyto") == note["name"]]
    assert len(answers) == 2  # one reply and one review state
    states = [n for n in answers if n.get("state")]
    assert [(s.get("statemodel"), s.get("state"), s.get("title")) for s in states] == [("Review", "Accepted", "Carol")]
    assert any(n.get("inreplyto") == answers[0].get("name") or n.get("inreplyto") == answers[1].get("name") for n in nodes)


def test_export_highlight_quadpoints_and_colors(client, doc):
    populate(client, doc)
    nodes = ET.fromstring(export(client, doc)).find(f"{NS}annots")
    highlight = next(n for n in nodes if n.tag == f"{NS}highlight")
    coords = [float(v) for v in highlight.get("coords").split(",")]
    assert len(coords) == 8
    assert highlight.get("color") == "#FFD400" and float(highlight.get("opacity")) == pytest.approx(0.6)
    square = next(n for n in nodes if n.tag == f"{NS}square")
    assert (square.get("color"), square.get("interior-color"), square.get("width")) == ("#2563EB", "#EEEEFF", "2")
    ink = next(n for n in nodes if n.tag == f"{NS}ink")
    assert len(ink.find(f"{NS}inklist").findall(f"{NS}gesture")) == 1


def test_export_of_a_document_without_comments_is_valid_and_empty(client, doc):
    root = ET.fromstring(export(client, doc))
    assert len(root.find(f"{NS}annots")) == 0
    response = client.get(f"{base(doc)}/comments/xfdf")
    assert response.headers["content-type"].startswith("application/vnd.adobe.xfdf")
    assert ".xfdf" in response.headers["content-disposition"]


def test_export_strips_characters_xml_cannot_hold(client, doc):
    add(client, doc, text="bell\x07 and tab\t and\x0bvertical tab")
    root = ET.fromstring(export(client, doc))
    assert root.find(f"{NS}annots")[0].find(f"{NS}contents").text == "bell and tab\t andvertical tab"


# ------------------------------------------------------------------ round trips
def test_round_trip_into_a_fresh_copy_preserves_every_comment(client, doc, sample_pdf):
    populate(client, doc)
    before = listing(client, doc)
    data = export(client, doc)
    target = blank_copy(client, sample_pdf)
    result = report(import_xfdf(client, target, data))
    assert result["skipped"] == 0 and result["warnings"] == []
    assert result["added"] == 13  # 9 comments (one on page two), 2 replies and 2 states
    after = listing(client, target)
    assert comparable(after) == comparable(before)
    assert after["count"] == before["count"] and after["authors"] == before["authors"]


def test_round_trip_keeps_names_so_the_thread_stays_linked(client, doc, sample_pdf):
    ids = populate(client, doc)
    before = by_xref(listing(client, doc), ids["note"])
    target = blank_copy(client, sample_pdf)
    import_xfdf(client, target, export(client, doc))
    after = next(c for c in listing(client, target)["comments"] if c["contents"].startswith("Look here &"))
    assert after["name"] == before["name"]
    assert [r["name"] for r in after["replies"]] == [r["name"] for r in before["replies"]]
    assert after["replies"][1]["parent"] == after["replies"][0]["xref"]


def test_importing_into_the_same_document_changes_nothing(client, doc):
    populate(client, doc)
    before = listing(client, doc)
    cursor = client.get(f"/api/documents/{doc['id']}").json()["data"]["cursor"]
    result = report(import_xfdf(client, doc, export(client, doc)))
    assert (result["added"], result["updated"], result["skipped"]) == (0, 0, 0)
    assert result["unchanged"] == before["count"] + 2  # every comment, reply and state is recognized
    assert comparable(listing(client, doc)) == comparable(before)
    assert result["pages"] == []
    assert client.get(f"/api/documents/{doc['id']}").json()["data"]["cursor"] == cursor + 1  # one history entry


def test_importing_twice_never_duplicates(client, doc, sample_pdf):
    populate(client, doc)
    data = export(client, doc)
    target = blank_copy(client, sample_pdf)
    import_xfdf(client, target, data)
    count = listing(client, target)["count"]
    second = report(import_xfdf(client, target, data))
    assert second["added"] == 0 and listing(client, target)["count"] == count


def test_import_updates_a_comment_that_has_the_same_name(client, doc):
    root = add(client, doc, text="First thought", author="Alice")
    data = export(client, doc).replace(b"First thought", b"Second thought")
    result = report(import_xfdf(client, doc, data))
    assert (result["added"], result["updated"]) == (0, 1)
    comment = by_xref(listing(client, doc), root)
    assert comment["contents"] == "Second thought" and listing(client, doc)["count"] == 1


def test_import_adds_replies_to_comments_already_in_the_document(client, doc, sample_pdf):
    root = add(client, doc, text="Question?", author="Alice")
    # a reviewer answers on their own copy of the same file
    theirs = blank_copy(client, sample_pdf)
    import_xfdf(client, theirs, export(client, doc))
    their_root = listing(client, theirs)["comments"][0]
    reply(client, theirs, their_root["xref"], "Yes.", "Rita")
    set_status(client, theirs, their_root["xref"], status="completed", author="Rita")
    result = report(import_xfdf(client, doc, export(client, theirs)))
    assert (result["added"], result["updated"]) == (2, 0)
    merged = by_xref(listing(client, doc), root)
    assert [r["contents"] for r in merged["replies"]] == ["Yes."]
    assert (merged["status"], merged["statusBy"]) == ("completed", "Rita")


def test_round_trip_on_a_rotated_page(client, doc, sample_pdf):
    client.post(f"{base(doc)}/pages/rotate", json={"pages": [0], "angle": 90})
    add(client, doc, point=[120, 60], text="rotated note")
    add(client, doc, kind="textbox", rect=[100, 200, 300, 260], text="rotated box", point=None)
    before = listing(client, doc)
    target = blank_copy(client, sample_pdf)
    client.post(f"{base(target)}/pages/rotate", json={"pages": [0], "angle": 90})
    assert report(import_xfdf(client, target, export(client, doc)))["added"] == 2
    assert comparable(listing(client, target)) == comparable(before)


def test_imported_comments_can_be_undone_as_one_step(client, doc, sample_pdf):
    populate(client, doc)
    target = blank_copy(client, sample_pdf)
    import_xfdf(client, target, export(client, doc))
    client.post(f"{base(target)}/undo")
    assert listing(client, target)["count"] == 0


def test_imported_comments_are_saved_in_the_pdf(client, doc, sample_pdf):
    populate(client, doc)
    target = blank_copy(client, sample_pdf)
    import_xfdf(client, target, export(client, doc))
    reopened = fitz.open(stream=current_pdf(client, target["id"]).tobytes())
    pages = [reopened[0], reopened[1]]
    assert sum(1 for page in pages for _ in page.annots() or []) > 8


# ------------------------------------------------------------------ files written by other programs
ACROBAT = """<?xml version="1.0" encoding="UTF-8"?>
<xfdf xmlns="http://ns.adobe.com/xfdf/" xml:space="preserve">
<f href="sample.pdf"/>
<ids original="ABC" modified="DEF"/>
<annots>
<text color="#FFFF00" creationdate="D:20230615101112+05'30'" date="D:20230615101112+05'30'" flags="print,nozoom,norotate"
  icon="Comment" name="note-1" page="0" rect="100,640,118,658" subject="Sticky Note" title="Priya"><contents>Check this figure</contents>
  <popup flags="print,nozoom,norotate" open="no" page="0" rect="120,560,320,660"/></text>
<text inreplyto="note-1" replyType="R" name="note-1-reply" page="0" rect="100,640,118,658" title="Omar" date="D:20230616090000Z"
  creationdate="D:20230616090000Z" flags="print,nozoom,norotate"><contents>Checked, fine.</contents></text>
<text inreplyto="note-1" replyType="R" name="note-1-state" page="0" rect="100,640,118,658" title="Omar" date="D:20230616090500Z"
  state="Accepted" statemodel="Review" flags="print,nozoom,norotate"><contents>Accepted set by Omar</contents></text>
<highlight color="#00FF00" coords="72,755,200,755,72,737,200,737" date="D:20230615101500+05'30'" flags="print" name="hl-1" page="0"
  rect="72,737,200,755" subject="Highlight" title="Priya" opacity="0.5"><contents-richtext><body xmlns="http://www.w3.org/1999/xhtml"><p>Rich <b>text</b> comment</p><p>second line</p></body></contents-richtext></highlight>
<freetext color="#FFEEAA" name="ft-1" page="1" rect="50,700,250,760" title="Priya" width="1"><defaultappearance>1 0 0 rg /Helv 14 Tf</defaultappearance><contents>Red text</contents></freetext>
<line name="ln-1" page="0" rect="300,300,400,400" start="300,300" end="400,400" head="None" tail="OpenArrow" color="#FF0000" width="2" title="Priya"/>
<ink name="ink-1" page="0" rect="10,10,60,60" color="#0000FF" width="3" title="Priya"><inklist><gesture>10,10;30,40;60,20</gesture></inklist></ink>
<circle name="c-1" page="0" rect="200,200,260,260" color="#00AA00" interior-color="#CCFFCC" title="Priya"/>
<popup page="0" rect="0,0,10,10"/>
</annots>
</xfdf>"""


def test_import_reads_a_file_written_the_way_acrobat_writes_it(client, doc):
    result = report(import_xfdf(client, doc, ACROBAT))
    assert (result["added"], result["skipped"]) == (8, 0)
    assert result["pages"] == [0, 1]
    data = listing(client, doc)
    by_text = {c["contents"]: c for c in data["comments"]}
    note = by_text["Check this figure"]
    assert (note["author"], note["subject"], note["name"]) == ("Priya", "Sticky Note", "note-1")
    assert note["created"] == "2023-06-15T04:41:12Z"  # 10:11:12 at +05:30
    assert [r["contents"] for r in note["replies"]] == ["Checked, fine."]
    assert (note["status"], note["statusBy"]) == ("accepted", "Omar")
    highlight = by_text["Rich text comment\nsecond line"]
    assert (highlight["type"], highlight["color"]) == ("Highlight", "#00ff00")
    assert "Invoice" in highlight["quote"]
    assert by_text["Red text"]["page"] == 1
    types = sorted(c["type"] for c in data["comments"])
    assert types == ["Circle", "FreeText", "Highlight", "Ink", "Line", "Text"]


def test_acrobat_file_places_things_where_acrobat_put_them(client, doc):
    import_xfdf(client, doc, ACROBAT)
    pdf = current_pdf(client, doc["id"])
    first, second = pdf[0], pdf[1]  # an annotation is only valid while its page object is alive
    note = next(a for a in first.annots() if a.type[1] == "Text" and a.info["content"] == "Check this figure")
    assert note.rect.x0 == pytest.approx(100) and note.rect.y0 == pytest.approx(842 - 658)  # PDF y counts up
    line = next(a for a in first.annots() if a.type[1] == "Line")
    assert [tuple(round(v) for v in p) for p in line.vertices] == [(300, 542), (400, 442)]
    assert line.line_ends == (0, 4)
    free = next(a for a in second.annots() if a.type[1] == "FreeText")
    assert re.fullmatch(r"1 0 0 rg /Helv 14(\.0)? Tf", pdf.xref_get_key(free.xref, "DA")[1])


def test_replies_are_imported_after_the_comments_they_answer_whatever_the_file_order(client, doc):
    xml = """<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots>
      <text page="0" rect="10,10,30,30" name="deep" inreplyto="mid" title="C"><contents>third</contents></text>
      <text page="0" rect="10,10,30,30" name="mid" inreplyto="top" title="B"><contents>second</contents></text>
      <text page="0" rect="10,10,30,30" name="top" title="A"><contents>first</contents></text>
    </annots></xfdf>"""
    result = report(import_xfdf(client, doc, xml))
    assert (result["added"], result["skipped"], result["warnings"]) == (3, 0, [])
    top = listing(client, doc)["comments"][0]
    assert top["contents"] == "first"
    assert [(r["contents"], r["depth"]) for r in top["replies"]] == [("second", 1), ("third", 2)]


def test_a_reply_to_a_missing_comment_becomes_a_comment_and_a_stray_state_is_dropped(client, doc):
    xml = """<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots>
      <text page="0" rect="10,10,30,30" name="a" inreplyto="gone" title="Rita"><contents>Orphan reply</contents></text>
      <text page="0" rect="10,10,30,30" name="b" inreplyto="gone" state="Accepted" statemodel="Review" title="Rita"/>
    </annots></xfdf>"""
    result = report(import_xfdf(client, doc, xml))
    assert (result["added"], result["skipped"]) == (1, 1)
    assert any("not in the document" in w for w in result["warnings"])
    assert [c["contents"] for c in listing(client, doc)["comments"]] == ["Orphan reply"]


def test_annotations_that_cannot_be_imported_are_skipped_and_explained(client, doc):
    xml = """<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots>
      <text page="9" rect="10,10,30,30" title="A"><contents>wrong page</contents></text>
      <text page="x" rect="10,10,30,30" title="A"/>
      <text page="0" rect="10,10,30" title="A"/>
      <text page="0" rect="nan,1,2,3" title="A"/>
      <text page="0" title="A"/>
      <highlight page="0" coords="1,2,3" title="A"/>
      <stamp page="0" rect="10,10,30,30"/>
      <widget page="0"/>
      <line page="0" start="1,2" title="A"/>
      <polygon page="0" title="A"><vertices>1,2;3,4</vertices></polygon>
      <text page="0" rect="100,100,120,120" name="good" title="Fine"><contents>kept</contents></text>
    </annots></xfdf>"""
    result = report(import_xfdf(client, doc, xml))
    assert (result["added"], result["skipped"]) == (1, 10)
    assert len(result["warnings"]) == 10 and all(w.startswith("Skipped ") for w in result["warnings"])
    assert any("page 9 does not exist" in w for w in result["warnings"])
    assert [c["contents"] for c in listing(client, doc)["comments"]] == ["kept"]


def test_a_name_used_by_another_kind_of_comment_gets_a_new_one(client, doc):
    xml = """<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots>
      <text page="0" rect="10,10,30,30" name="same"><contents>one</contents></text>
      <square page="0" rect="50,50,90,90" name="same"/>
    </annots></xfdf>"""
    result = report(import_xfdf(client, doc, xml))
    assert result["added"] == 2 and any("already used" in w for w in result["warnings"])
    names = [c["name"] for c in listing(client, doc)["comments"]]
    assert len(set(names)) == 2 and "same" in names


# ------------------------------------------------------------------ untrusted XML
def refused(client, doc, xml: bytes | str, status: int = 400) -> str:
    response = import_xfdf(client, doc, xml)
    assert response.status_code == status, response.text
    assert response.json()["ok"] is False
    assert listing(client, doc)["count"] == 0  # nothing was imported
    return response.json()["error"]


def test_external_entities_are_refused_and_never_read(client, doc, tmp_path):
    secret = tmp_path / "passwd"
    secret.write_text(FAKE_PASSWD)
    xml = f"""<?xml version="1.0"?>
<!DOCTYPE xfdf [<!ENTITY secret SYSTEM "file://{secret}">]>
<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots><text page="0" rect="1,1,20,20" title="&secret;"><contents>&secret;</contents></text></annots></xfdf>"""
    error = refused(client, doc, xml)
    assert "document type declaration" in error and "SECRET-CANARY" not in error
    assert "SECRET-CANARY" not in str([c["contents"] for c in listing(client, doc)["comments"]])


def test_entity_expansion_bombs_are_refused_quickly(client, doc):
    lols = "".join(f'<!ENTITY l{i} "{"&l%d;" % (i - 1) * 10}">' for i in range(1, 9))
    xml = f'<?xml version="1.0"?><!DOCTYPE xfdf [<!ENTITY l0 "lol">{lols}]><xfdf xmlns="http://ns.adobe.com/xfdf/"><annots><text page="0" rect="1,1,2,2"><contents>&l8;</contents></text></annots></xfdf>'
    started = time.perf_counter()
    refused(client, doc, xml)
    assert time.perf_counter() - started < 2


def test_even_an_empty_doctype_is_refused(client, doc):
    refused(client, doc, '<!DOCTYPE xfdf><xfdf xmlns="http://ns.adobe.com/xfdf/"><annots/></xfdf>')


def test_parameter_entities_and_external_dtds_are_refused(client, doc):
    refused(client, doc, '<!DOCTYPE xfdf SYSTEM "http://127.0.0.1:9/evil.dtd"><xfdf xmlns="http://ns.adobe.com/xfdf/"><annots/></xfdf>')
    refused(client, doc, '<!DOCTYPE xfdf [<!ENTITY % p SYSTEM "file:///etc/passwd">%p;]><xfdf xmlns="http://ns.adobe.com/xfdf/"><annots/></xfdf>')


def test_undefined_entities_and_broken_xml_are_refused(client, doc):
    assert "not valid XML" in refused(client, doc, '<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots><text page="0">&nope;</text></annots></xfdf>')
    assert "not valid XML" in refused(client, doc, "<xfdf><annots>")
    assert "not valid XML" in refused(client, doc, b"\x00\x01 definitely not xml")
    assert "not valid XML" in refused(client, doc, "plain text")


def test_wrong_root_and_empty_files_are_refused(client, doc):
    assert "not an XFDF file" in refused(client, doc, "<html><body/></html>")
    assert "not an XFDF file" in refused(client, doc, '<other xmlns="urn:example"/>')
    assert client.post(f"{base(doc)}/comments/xfdf", files={"file": ("e.xfdf", b"", "application/xml")}).status_code == 400


def test_oversized_files_are_refused(client, doc):
    big = b"<xfdf><annots>" + b"<text page='0' rect='1,1,2,2'/>" * 300_000 + b"</annots></xfdf>"
    assert len(big) > 8 * 1024 * 1024
    refused(client, doc, big, status=413)


def test_deep_nesting_is_refused(client, doc):
    xml = '<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots><text page="0" rect="1,1,9,9">' + "<a>" * 200 + "</a>" * 200 + "</text></annots></xfdf>"
    assert "nested too deeply" in refused(client, doc, xml)


def test_too_many_elements_and_annotations_are_refused(client, doc):
    many = '<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots>' + '<text page="0" rect="1,1,9,9"/>' * 10_001 + "</annots></xfdf>"
    assert "more than 10000 annotations" in refused(client, doc, many)
    flood = '<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots>' + "<a/>" * 200_001 + "</annots></xfdf>"
    assert "too many elements" in refused(client, doc, flood)


def test_bad_numbers_in_lists_are_refused_with_the_annotation_named(client, doc):
    ink = '<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots><ink page="0"><inklist><gesture>1,2;abc</gesture></inklist></ink></annots></xfdf>'
    assert "ink #1" in refused(client, doc, ink)
    huge = '<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots><polygon page="0"><vertices>1,2;3,1e999</vertices></polygon></annots></xfdf>'
    assert "out of range" in refused(client, doc, huge)
    odd = '<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots><polygon page="0"><vertices>1,2;3</vertices></polygon></annots></xfdf>'
    assert "odd number" in refused(client, doc, odd)


def test_a_refused_import_leaves_the_document_and_its_history_alone(client, doc):
    root = add(client, doc)
    cursor = client.get(f"/api/documents/{doc['id']}").json()["data"]["cursor"]
    assert import_xfdf(client, doc, "<!DOCTYPE x><xfdf/>").status_code == 400
    assert client.get(f"/api/documents/{doc['id']}").json()["data"]["cursor"] == cursor
    assert [c["xref"] for c in listing(client, doc)["comments"]] == [root]


def test_text_is_taken_literally_not_interpreted(client, doc):
    xml = """<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots>
      <text page="0" rect="10,10,30,30" name="n" title="&lt;script&gt;alert(1)&lt;/script&gt;" subject="${jndi:ldap://x}">
      <contents>=cmd|' /C calc'!A0 &amp;lt; ../../etc/passwd</contents></text></annots></xfdf>"""
    assert report(import_xfdf(client, doc, xml))["added"] == 1
    comment = listing(client, doc)["comments"][0]
    assert comment["author"] == "<script>alert(1)</script>" and comment["subject"] == "${jndi:ldap://x}"
    assert comment["contents"] == "=cmd|' /C calc'!A0 &lt; ../../etc/passwd"


def test_overlong_values_are_clipped(client, doc):
    long = "A" * 50_000
    xml = f'<xfdf xmlns="http://ns.adobe.com/xfdf/"><annots><text page="0" rect="10,10,30,30" title="{long}" name="{long}"><contents>{long}</contents></text></annots></xfdf>'
    assert report(import_xfdf(client, doc, xml))["added"] == 1
    comment = listing(client, doc)["comments"][0]
    assert len(comment["author"]) == 200 and len(comment["name"]) == 200 and len(comment["contents"]) == 20000


def test_xfdf_in_other_encodings_is_read(client, doc):
    xml = '<?xml version="1.0" encoding="UTF-16"?><xfdf xmlns="http://ns.adobe.com/xfdf/"><annots><text page="0" rect="1,1,9,9"><contents>café 中文</contents></text></annots></xfdf>'
    assert report(import_xfdf(client, doc, xml.encode("utf-16")))["added"] == 1
    assert listing(client, doc)["comments"][0]["contents"] == "café 中文"
