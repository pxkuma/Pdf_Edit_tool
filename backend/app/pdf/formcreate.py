"""Creating form fields of every type (Acrobat's "Prepare form").

Fields are created with MuPDF (which also draws their appearance streams), then adjusted on the raw
objects: radio buttons become kids of one group field with distinct export values, the AcroForm gets the
default resources other viewers need, and empty signature fields get a plain box.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pymupdf as fitz

from . import formnames, formobj
from .formerror import FormError
from .formprops import MIN_FIELD, FieldProps, apply_props
from .geometry import Rect4, from_display_rect

KINDS = {
    "text": fitz.PDF_WIDGET_TYPE_TEXT,
    "checkbox": fitz.PDF_WIDGET_TYPE_CHECKBOX,
    "radio": fitz.PDF_WIDGET_TYPE_RADIOBUTTON,
    "combobox": fitz.PDF_WIDGET_TYPE_COMBOBOX,
    "listbox": fitz.PDF_WIDGET_TYPE_LISTBOX,
    "button": fitz.PDF_WIDGET_TYPE_BUTTON,
    "signature": fitz.PDF_WIDGET_TYPE_SIGNATURE,
}
BORDER = (0.45, 0.45, 0.55)
BUTTON_FILL = (0.85, 0.85, 0.87)
MAX_BATCH = 500
_TEMP_NAME = "PDFStudioNewRadio"


@dataclass(frozen=True)
class NewField:
    kind: str
    rect: Rect4  # display space
    props: FieldProps = field(default_factory=FieldProps)
    value: str | bool | None = None


def _base_widget(kind: str, name: str, rect: fitz.Rect) -> fitz.Widget:
    widget = fitz.Widget()
    widget.field_type = KINDS[kind]
    widget.field_name = name
    widget.rect = rect
    widget.border_color = BORDER
    widget.border_width = 1
    widget.text_fontsize = 0
    if kind == "button":
        widget.fill_color = BUTTON_FILL
        widget.border_style = "B"
        widget.button_caption = "Button"
        widget.text_fontsize = 10
    elif kind in ("checkbox", "radio"):
        widget.field_value = False
    elif kind in ("combobox", "listbox"):
        widget.choice_values = []
    return widget


def _target_rect(page: fitz.Page, rect: Rect4) -> fitz.Rect:
    target = from_display_rect(page, rect)
    if target.width < MIN_FIELD or target.height < MIN_FIELD:
        raise FormError("Field area is too small.")
    if not target.intersects(page.rect):
        raise FormError("The field must be on the page.")
    return target


def _choose_name(index: dict, new: NewField, uniquify: bool) -> str:
    if not new.props.name:
        return formnames.auto_name(index, new.kind)
    name = formnames.clean_name(new.props.name)
    joins_group = new.kind == "radio" and index.get(name, ("",))[0] == "radio"
    return name if joins_group or not uniquify else formnames.unique_variant(index, name)


def _group_states(doc: fitz.Document, group: int) -> set[str]:
    states: set[str] = set()
    for kid in formobj.kids_of(doc, group) or [group]:
        states.update(formobj.decode_name(name) for name in formobj.on_state_names(doc, kid))
    return states


def _link_radio(doc: fitz.Document, xref: int, join: int | None, export: str | None) -> None:
    if join is None:
        group = formobj.to_radio_group(doc, xref)
        taken: set[str] = set()
    else:
        group = formobj.to_radio_group(doc, join)
        taken = _group_states(doc, group)
        formobj.add_kid(doc, group, xref)
    if export is not None and export in taken:
        raise FormError(f"Another button of this group already uses the export value “{export}”.")
    number = len(taken) + 1
    while f"Choice{number}" in taken:
        number += 1
    formobj.rename_on_state(doc, xref, export or f"Choice{number}")


def create_field(doc: fitz.Document, page: fitz.Page, new: NewField, uniquify: bool = False) -> dict:
    if new.kind not in KINDS:
        raise FormError("Unknown field type.")
    index = formnames.field_index(doc)
    name = _choose_name(index, new, uniquify)
    join = formnames.resolve_new_name(index, name, new.kind)
    widget = _base_widget(new.kind, _TEMP_NAME if join is not None else name, _target_rect(page, new.rect))
    if new.kind == "text" and isinstance(new.value, str):
        widget.field_value = new.value
    xref = page.add_widget(widget).xref
    if new.kind == "radio":
        _link_radio(doc, xref, join, new.props.export_value)
    props = replace(new.props, name=None, rect=None, export_value=None if new.kind == "radio" else new.props.export_value)
    apply_props(doc, page, page.load_widget(xref), new.kind, props)
    if new.kind in ("checkbox", "radio") and new.value:
        from .forms import set_values  # late import: forms lists fields with formprops

        set_values(doc, [{"page": page.number, "xref": xref, "value": True}])
    formobj.ensure_defaults(doc)
    if new.kind == "signature":
        signed = any(w.is_signed for p in doc for w in p.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]))
        formobj.fix_sig_flags(doc, signed)
    return {"xref": xref, "page": page.number, "name": name, "kind": new.kind}


def create_fields(doc: fitz.Document, items: list[tuple[int, NewField]], uniquify: bool = True) -> list[dict]:
    if len(items) > MAX_BATCH:
        raise FormError(f"At most {MAX_BATCH} fields can be added at once.")
    created = []
    for page_index, new in items:
        if not 0 <= page_index < doc.page_count:
            raise FormError("Page out of range.")
        created.append(create_field(doc, doc[page_index], new, uniquify))
    return created

