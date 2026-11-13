"""Form authoring engine: every field type survives create -> save -> reload -> fill, with real /AP streams."""

from __future__ import annotations

import re

import pymupdf as fitz
import pytest

from app.pdf import forms
from app.pdf.formcreate import NewField, create_field, create_fields
from app.pdf.formerror import FormError
from app.pdf.formformat import FieldFormat
from app.pdf.formprops import FieldProps


def blank() -> fitz.Document:
    doc = fitz.open()
    doc.new_page()
    return doc


def reload(doc: fitz.Document) -> fitz.Document:
    return fitz.open("pdf", doc.tobytes(garbage=1, deflate=True))


def add(doc: fitz.Document, kind: str, rect, value=None, **props) -> dict:
    return create_field(doc, doc[0], NewField(kind, rect, FieldProps(**props), value))


def by_name(doc: fitz.Document, name: str) -> list[dict]:
    return [f for f in forms.list_fields(doc) if f["name"] == name]


def fill(doc: fitz.Document, field: dict, value) -> None:
    forms.set_values(doc, [{"page": field["page"], "xref": field["xref"], "value": value}])


def appearance_xrefs(doc: fitz.Document, xref: int) -> list[int]:
    """Every appearance stream of a widget (both states of a button)."""
    kind, value = doc.xref_get_key(xref, "AP/N")
    assert kind in ("xref", "dict"), f"widget {xref} has no normal appearance"
    return [int(n) for n in re.findall(r"(\d+) 0 R", value)]


def assert_has_appearance(doc: fitz.Document, field: dict) -> None:
    for stream in appearance_xrefs(doc, field["xref"]):
        assert doc.xref_get_key(stream, "Subtype")[1] == "/Form"
        assert doc.xref_get_key(stream, "BBox")[0] == "array"
        assert doc.xref_stream(stream) is not None


def test_text_field_round_trip_with_properties():
    doc = blank()
    add(doc, "text", (72, 72, 300, 92), name="full_name", tooltip="Your full name", required=True,
        align="center", font="Times", font_size=11, text_color="#112233", fill_color="#eef2ff", max_length=40)
    doc = reload(doc)
    (field,) = by_name(doc, "full_name")
    assert field["type"] == "text" and field["required"] and field["tooltip"] == "Your full name"
    assert field["align"] == "center" and field["font"] == "Times" and field["fontSize"] == 11
    assert field["textColor"] == "#112233" and field["fillColor"] == "#eef2ff" and field["maxLength"] == 40
    assert_has_appearance(doc, field)
    fill(doc, field, "Jane Doe")
    doc = reload(doc)
    (field,) = by_name(doc, "full_name")
    assert field["value"] == "Jane Doe"
    assert b"Jane Doe" in doc.xref_stream(appearance_xrefs(doc, field["xref"])[0])


def test_multiline_and_comb_text():
    doc = blank()
    add(doc, "text", (72, 72, 300, 140), name="notes", multiline=True)
    add(doc, "text", (72, 160, 200, 180), name="pin", comb=True, max_length=4)
    doc = reload(doc)
    assert by_name(doc, "notes")[0]["multiline"]
    pin = by_name(doc, "pin")[0]
    assert pin["comb"] and pin["maxLength"] == 4
    fill(doc, pin, "123456")
    assert by_name(reload(doc), "pin")[0]["value"] == "1234"


def test_comb_needs_max_length():
    doc = blank()
    with pytest.raises(FormError, match="comb"):
        add(doc, "text", (72, 72, 200, 92), name="pin", comb=True)


def test_number_format_round_trip_and_validation():
    doc = blank()
    add(doc, "text", (72, 72, 200, 92), name="amount", format=FieldFormat("number", decimals=2))
    doc = reload(doc)
    (field,) = by_name(doc, "amount")
    assert field["format"]["kind"] == "number" and field["format"]["decimals"] == 2
    assert "AFNumber_Format" in doc.xref_object(field["xref"], compressed=False) or doc.xref_get_key(field["xref"], "AA/F")[0] != "null"
    fill(doc, field, "1,234.5")
    assert by_name(reload(doc), "amount")[0]["value"] == "1234.50"
    with pytest.raises(FormError, match="not a number"):
        fill(doc, field, "abc")


def test_date_format_round_trip_and_validation():
    doc = blank()
    add(doc, "text", (72, 72, 200, 92), name="when", format=FieldFormat("date", pattern="dd/mm/yyyy"))
    doc = reload(doc)
    (field,) = by_name(doc, "when")
    assert field["format"] == {"kind": "date", "decimals": 2, "pattern": "dd/mm/yyyy"}
    fill(doc, field, "31/12/2024")
    assert by_name(reload(doc), "when")[0]["value"] == "31/12/2024"
    with pytest.raises(FormError, match="date format"):
        fill(doc, field, "12/31/2024")


def test_checkbox_with_export_value():
    doc = blank()
    add(doc, "checkbox", (72, 72, 86, 86), name="agree", export_value="I agree")
    doc = reload(doc)
    (field,) = by_name(doc, "agree")
    assert field["onState"] == "I agree" and field["value"] is False
    assert_has_appearance(doc, field)
    assert len(appearance_xrefs(doc, field["xref"])) == 2  # on and Off
    fill(doc, field, True)
    doc = reload(doc)
    (field,) = by_name(doc, "agree")
    assert field["value"] is True
    assert "/V/I#20agree" in doc.xref_object(field["xref"], compressed=True)  # a name, escaped
    fill(doc, field, False)
    assert by_name(reload(doc), "agree")[0]["value"] is False


def test_radio_group_shares_name_with_distinct_export_values():
    doc = blank()
    add(doc, "radio", (72, 72, 86, 86), name="size", export_value="S")
    add(doc, "radio", (92, 72, 106, 86), name="size", export_value="M")
    add(doc, "radio", (112, 72, 126, 86), name="size")
    doc = reload(doc)
    buttons = by_name(doc, "size")
    assert [b["onState"] for b in buttons] == ["S", "M", "Choice3"]
    assert all(b["group"] == 3 for b in buttons)
    parents = {doc.xref_get_key(b["xref"], "Parent")[1] for b in buttons}
    assert len(parents) == 1, "all buttons must be kids of one field"
    group = int(parents.pop().split()[0])
    assert doc.xref_get_key(group, "T") == ("string", "size")
    fields_array = doc.xref_get_key(doc.pdf_catalog(), "AcroForm/Fields")[1]
    assert f"{group} 0 R" in fields_array and all(f"{b['xref']} 0 R" not in fields_array for b in buttons)
    for button in buttons:
        assert_has_appearance(doc, button)

    fill(doc, buttons[1], True)
    doc = reload(doc)
    assert [b["value"] for b in by_name(doc, "size")] == [False, True, False]
    assert doc.xref_get_key(group, "V") == ("name", "/M")
    fill(doc, by_name(doc, "size")[0], True)
    doc = reload(doc)
    assert [b["value"] for b in by_name(doc, "size")] == [True, False, False]
    assert doc.xref_get_key(group, "V") == ("name", "/S")


def test_radio_export_values_must_differ():
    doc = blank()
    add(doc, "radio", (72, 72, 86, 86), name="size", export_value="S")
    with pytest.raises(FormError, match="export value"):
        add(doc, "radio", (92, 72, 106, 86), name="size", export_value="S")


def test_dropdown_with_labels_and_editable_option():
    doc = blank()
    add(doc, "combobox", (72, 72, 220, 92), name="fruit", options=(("a", "Apple"), ("b", "Banana")))
    add(doc, "combobox", (72, 100, 220, 120), name="free", options=(("x", "x"),), editable=True)
    doc = reload(doc)
    fruit = by_name(doc, "fruit")[0]
    assert fruit["choices"] == [{"value": "a", "label": "Apple"}, {"value": "b", "label": "Banana"}]
    assert fruit["options"] == ["a", "b"] and not fruit["editable"]
    fill(doc, fruit, "b")
    doc = reload(doc)
    fruit = by_name(doc, "fruit")[0]
    assert fruit["value"] == "b"
    assert b"Banana" in doc.xref_stream(appearance_xrefs(doc, fruit["xref"])[0])  # shows the label
    with pytest.raises(FormError, match="not one of the options"):
        fill(doc, fruit, "cherry")
    free = by_name(doc, "free")[0]
    assert free["editable"]
    fill(doc, free, "typed in")
    assert by_name(reload(doc), "free")[0]["value"] == "typed in"


def test_multi_select_list_box():
    doc = blank()
    add(doc, "listbox", (72, 72, 220, 140), name="langs", multi_select=True,
        options=(("en", "English"), ("de", "German"), ("fr", "French")))
    doc = reload(doc)
    (field,) = by_name(doc, "langs")
    assert field["multiSelect"] and field["value"] == []
    fill(doc, field, ["en", "fr"])
    doc = reload(doc)
    (field,) = by_name(doc, "langs")
    assert field["value"] == ["en", "fr"]
    stream = doc.xref_stream(appearance_xrefs(doc, field["xref"])[0])
    assert stream.count(b" re f") >= 2 and b"English" in stream  # selection highlights + labels


def test_single_select_list_box_refuses_several_values():
    doc = blank()
    add(doc, "listbox", (72, 72, 220, 140), name="one", options=(("a", "a"), ("b", "b")))
    field = by_name(doc, "one")[0]
    with pytest.raises(FormError, match="only one"):
        fill(doc, field, ["a", "b"])


@pytest.mark.parametrize(("action", "url", "expected"), [
    ("reset", None, "/ResetForm"),
    ("print", None, "/Named"),
    ("url", "https://example.org/help", "/URI"),
    ("submit", "https://example.org/submit", "/SubmitForm"),
])
def test_push_button_actions(action, url, expected):
    doc = blank()
    add(doc, "button", (72, 72, 172, 96), name="go", caption="Go", action=action, url=url)
    doc = reload(doc)
    (field,) = by_name(doc, "go")
    assert field["type"] == "button" and field["caption"] == "Go" and field["action"] == action
    assert doc.xref_get_key(field["xref"], "A/S")[1] == expected
    if url:
        assert field["url"] == url
    assert_has_appearance(doc, field)


def test_button_url_is_required():
    doc = blank()
    with pytest.raises(FormError, match="web address"):
        add(doc, "button", (72, 72, 172, 96), name="go", action="url")


def test_empty_signature_field():
    doc = blank()
    add(doc, "signature", (72, 72, 272, 122), name="Sign here")
    doc = reload(doc)
    (field,) = by_name(doc, "Sign here")
    assert field["type"] == "signature" and not field["signed"]
    stream = doc.xref_stream(appearance_xrefs(doc, field["xref"])[0])
    assert b"re f" in stream and b"SIGN" not in stream  # a plain box, not MuPDF's marker
    assert doc.get_sigflags() == 1  # signature fields exist, nothing signed (no AppendOnly)


def test_acroform_gets_default_resources():
    doc = reload_after(lambda d: add(d, "text", (72, 72, 200, 92), name="a"))
    form = doc.xref_get_key(doc.pdf_catalog(), "AcroForm")
    text = doc.xref_object(int(form[1].split()[0])) if form[0] == "xref" else form[1]
    assert "/Helv" in text and "/DA" in text and "NeedAppearances true" not in text


def reload_after(action) -> fitz.Document:
    doc = blank()
    action(doc)
    return reload(doc)


# ------------------------------------------------------------------ names
def test_auto_names_are_unique_and_acrobat_style():
    doc = blank()
    first = add(doc, "text", (72, 72, 200, 92))
    second = add(doc, "text", (72, 100, 200, 120))
    box = add(doc, "checkbox", (72, 130, 86, 144))
    assert (first["name"], second["name"], box["name"]) == ("Text1", "Text2", "Check Box1")


@pytest.mark.parametrize("bad", ["   ", "a.b", "tab\there", "x" * 121])
def test_invalid_names_are_rejected(bad):
    doc = blank()
    with pytest.raises(FormError):
        add(doc, "text", (72, 72, 200, 92), name=bad)


def test_duplicate_names_are_rejected_except_radio_groups():
    doc = blank()
    add(doc, "text", (72, 72, 200, 92), name="email")
    with pytest.raises(FormError, match="already exists"):
        add(doc, "text", (72, 100, 200, 120), name="email")
    with pytest.raises(FormError, match="already exists"):
        add(doc, "radio", (72, 130, 86, 144), name="email")
    add(doc, "radio", (72, 150, 86, 164), name="choice")
    add(doc, "radio", (92, 150, 106, 164), name="choice")  # joins the group
    assert len(by_name(doc, "choice")) == 2


def test_batch_uniquifies_names():
    doc = blank()
    add(doc, "text", (72, 72, 200, 92), name="Name")
    created = create_fields(doc, [(0, NewField("text", (72, 100, 200, 120), FieldProps(name="Name"))),
                                  (0, NewField("text", (72, 130, 200, 150), FieldProps(name="Name")))])
    assert [c["name"] for c in created] == ["Name_2", "Name_3"]


def test_rename_enforces_uniqueness_and_renames_radio_group():
    doc = blank()
    add(doc, "text", (72, 72, 200, 92), name="first")
    add(doc, "text", (72, 100, 200, 120), name="second")
    add(doc, "radio", (72, 130, 86, 144), name="grp")
    add(doc, "radio", (92, 130, 106, 144), name="grp")
    second = by_name(doc, "second")[0]
    with pytest.raises(FormError, match="already exists"):
        forms.update_field(doc, 0, second["xref"], FieldProps(name="first"))
    forms.update_field(doc, 0, second["xref"], FieldProps(name="renamed"))
    radio = by_name(doc, "grp")[0]
    forms.update_field(doc, 0, radio["xref"], FieldProps(name="colour"))
    doc = reload(doc)
    assert by_name(doc, "renamed") and len(by_name(doc, "colour")) == 2 and not by_name(doc, "grp")


# ------------------------------------------------------------------ editing
def test_update_properties_and_rect():
    doc = blank()
    created = add(doc, "text", (72, 72, 200, 92), name="t")
    forms.update_field(doc, 0, created["xref"], FieldProps(
        rect=(100, 200, 300, 230), read_only=True, border_color="none", fill_color="none", default_value="hello"))
    doc = reload(doc)
    (field,) = by_name(doc, "t")
    assert field["rect"] == pytest.approx([100, 200, 300, 230], abs=0.01)
    assert field["readOnly"] and field["borderColor"] is None and field["fillColor"] is None
    assert field["defaultValue"] == "hello"


def test_update_options_and_radio_group_flags():
    doc = blank()
    add(doc, "radio", (72, 72, 86, 86), name="r")
    add(doc, "radio", (92, 72, 106, 86), name="r")
    first = by_name(doc, "r")[0]
    forms.update_field(doc, 0, first["xref"], FieldProps(required=True, export_value="Yes please"))
    doc = reload(doc)
    buttons = by_name(doc, "r")
    assert all(b["required"] for b in buttons)
    assert buttons[0]["onState"] == "Yes please"


def test_delete_radio_button_keeps_group_consistent():
    doc = blank()
    add(doc, "radio", (72, 72, 86, 86), name="r")
    add(doc, "radio", (92, 72, 106, 86), name="r")
    first, second = by_name(doc, "r")
    forms.delete_field(doc, 0, first["xref"])
    doc = reload(doc)
    (left,) = by_name(doc, "r")
    assert left["group"] == 1
    forms.delete_field(doc, 0, left["xref"])
    doc = reload(doc)
    assert forms.list_fields(doc) == []
    assert doc.xref_get_key(doc.pdf_catalog(), "AcroForm/Fields")[1] in ("[]", "null") or "R" not in \
        doc.xref_get_key(doc.pdf_catalog(), "AcroForm/Fields")[1]


def test_existing_fill_still_works_on_fields_from_other_tools():
    """Forms made by PyMuPDF directly (no PDF Studio post-processing) still fill as before."""
    doc = blank()
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "legacy"
    widget.rect = fitz.Rect(72, 72, 200, 92)
    doc[0].add_widget(widget)
    doc = reload(doc)
    fill(doc, by_name(doc, "legacy")[0], "ok")
    assert by_name(reload(doc), "legacy")[0]["value"] == "ok"
