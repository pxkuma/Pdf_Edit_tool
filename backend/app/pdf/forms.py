"""Interactive form (AcroForm) fields: list, fill, edit properties, remove.

Creating fields lives in :mod:`formcreate`, properties in :mod:`formprops`, tab order in :mod:`formorder`
and field recognition in :mod:`formdetect`.
"""

from __future__ import annotations

from dataclasses import replace

import pymupdf as fitz

from . import formobj
from .formap import choice_labels, selected_values
from .formcreate import NewField, create_field
from .formerror import FormError
from .formformat import coerce_value, parse_format
from .formprops import FieldProps, apply_props, read_props, refresh_appearance
from .geometry import to_display_rect

FIELD_TYPES = {
    fitz.PDF_WIDGET_TYPE_TEXT: "text",
    fitz.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    fitz.PDF_WIDGET_TYPE_COMBOBOX: "combobox",
    fitz.PDF_WIDGET_TYPE_LISTBOX: "listbox",
    fitz.PDF_WIDGET_TYPE_SIGNATURE: "signature",
    fitz.PDF_WIDGET_TYPE_BUTTON: "button",
}
MAX_VALUE = 20000

__all__ = ["FormError", "FIELD_TYPES", "list_fields", "list_fields_on_page", "set_values", "add_field",
           "update_field", "delete_field"]


def list_fields(doc: fitz.Document) -> list[dict]:
    fields = []
    for page in doc:
        fields.extend(list_fields_on_page(page))
    return fields


def list_fields_on_page(page: fitz.Page) -> list[dict]:
    """The page's fields in tab order (the order of the page's /Annots array)."""
    doc = page.parent
    fields = []
    for order, widget in enumerate(page.widgets() or []):
        kind = FIELD_TYPES.get(widget.field_type, "unknown")
        field = {
            "xref": widget.xref,
            "page": page.number,
            "name": widget.field_name or f"field_{widget.xref}",
            "label": widget.field_label or "",
            "type": kind,
            "value": _value(doc, widget, kind),
            "options": [value for value, _label in _choices(widget)] if kind in ("combobox", "listbox") else [],
            "onState": _on_state(widget) if kind in ("checkbox", "radio") else None,
            "rect": to_display_rect(page, widget.rect),
            "readOnly": bool(widget.field_flags & fitz.PDF_FIELD_IS_READ_ONLY),
            "required": bool(widget.field_flags & fitz.PDF_FIELD_IS_REQUIRED),
            "multiline": bool(widget.field_flags & fitz.PDF_TX_FIELD_IS_MULTILINE) if kind == "text" else False,
            "maxLength": widget.text_maxlen or 0,
            "tabIndex": order,
        }
        field.update(read_props(doc, widget, kind))
        fields.append(field)
    return fields


def _choices(widget: fitz.Widget) -> list[tuple[str, str]]:
    return choice_labels(widget)


def _on_state(widget: fitz.Widget) -> str:
    try:
        state = widget.on_state()
    except Exception:  # noqa: BLE001
        state = "Yes"
    return formobj.decode_name(state) if isinstance(state, str) and state else "Yes"


def _value(doc: fitz.Document, widget: fitz.Widget, kind: str):
    if kind in ("checkbox", "radio"):
        # A radio button is on when its own appearance state is (the group value names one button).
        state = doc.xref_get_key(widget.xref, "AS")
        if state[0] == "name":
            return state[1] not in ("/Off", "")
        return widget.field_value not in (None, "", "Off", False)
    if kind == "listbox" and widget.field_flags & fitz.PDF_CH_FIELD_IS_MULTI_SELECT:
        return selected_values(doc, formobj.field_head(doc, widget.xref))
    value = widget.field_value
    return "" if value is None else value


def _find_widget(doc: fitz.Document, page_index: int, xref: int) -> tuple[fitz.Page, fitz.Widget]:
    if not 0 <= page_index < doc.page_count:
        raise FormError("Page out of range.")
    page = doc[page_index]
    for widget in page.widgets() or []:
        if widget.xref == xref:
            return page, widget
    raise FormError("Form field not found.")


def _set_button(doc: fitz.Document, widget: fitz.Widget, kind: str, value) -> None:
    on = _on_state(widget)
    turn_on = bool(value) and value != "Off"
    widget.field_value = (on if kind == "checkbox" else True) if turn_on else False
    widget.update()
    head = formobj.field_head(doc, widget.xref)
    if kind == "radio" and not turn_on:
        doc.xref_set_key(widget.xref, "AS", "/Off")
        current = doc.xref_get_key(head, "V")[1]
        if current in (formobj.pdf_name(on), f"({on})"):
            formobj.set_name_value(doc, head, "Off")
        return
    formobj.set_name_value(doc, head, on if turn_on else "Off")


def _set_choice(doc: fitz.Document, page: fitz.Page, widget: fitz.Widget, kind: str, value) -> None:
    allowed = {v for v, _label in _choices(widget)}
    multi = kind == "listbox" and widget.field_flags & fitz.PDF_CH_FIELD_IS_MULTI_SELECT
    values = [str(v) for v in value] if isinstance(value, list) else ([] if value in (None, "") else [str(value)])
    if len(values) > 1 and not multi:
        raise FormError(f"“{widget.field_name}” accepts only one choice.")
    editable = kind == "combobox" and widget.field_flags & fitz.PDF_CH_FIELD_IS_EDIT
    if not editable and any(v not in allowed for v in values):
        raise FormError(f"“{values[0]}” is not one of the options of “{widget.field_name}”.")
    widget.field_value = values[0] if values else ""
    widget.update()
    head = formobj.field_head(doc, widget.xref)
    if multi and len(values) > 1:
        doc.xref_set_key(head, "V", "[" + "".join(fitz.get_pdf_str(v) for v in values) + "]")
    elif not values:
        formobj.del_key(doc, head, "V")
    refresh_appearance(doc, page, widget.xref, kind)


def _set_text(widget: fitz.Widget, value) -> None:
    text = "" if value is None else str(value)[:MAX_VALUE]
    text = coerce_value(parse_format(widget.script_format), text)
    if widget.text_maxlen and len(text) > widget.text_maxlen:
        text = text[: widget.text_maxlen]
    widget.field_value = text
    widget.update()


def set_values(doc: fitz.Document, values: list[dict]) -> set[int]:
    changed: set[int] = set()
    for item in values:
        page, widget = _find_widget(doc, int(item["page"]), int(item["xref"]))
        if widget.field_flags & fitz.PDF_FIELD_IS_READ_ONLY:
            continue
        kind = FIELD_TYPES.get(widget.field_type, "unknown")
        value = item.get("value")
        if kind in ("checkbox", "radio"):
            _set_button(doc, widget, kind, value)
        elif kind in ("combobox", "listbox"):
            _set_choice(doc, page, widget, kind, value)
        elif kind == "text":
            _set_text(widget, value)
        else:
            continue
        changed.add(page.number)
    return changed


def add_field(page: fitz.Page, kind: str, rect: tuple, name: str, value: str | bool | None,
              props: FieldProps | None = None) -> int:
    base = props or FieldProps()
    if name and not base.name:
        base = replace(base, name=name)
    created = create_field(page.parent, page, NewField(kind=kind, rect=tuple(rect), props=base, value=value))
    return created["xref"]


def update_field(doc: fitz.Document, page_index: int, xref: int, props: FieldProps) -> dict:
    page, widget = _find_widget(doc, page_index, xref)
    kind = FIELD_TYPES.get(widget.field_type, "unknown")
    if kind == "unknown":
        raise FormError("This field type cannot be edited.")
    if kind == "signature" and widget.is_signed:
        raise FormError("A signed signature field cannot be changed.")
    apply_props(doc, page, widget, kind, props)
    return {"xref": xref, "page": page_index}


def delete_field(doc: fitz.Document, page_index: int, xref: int) -> None:
    page, widget = _find_widget(doc, page_index, xref)
    if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE and widget.is_signed:
        raise FormError("A signed signature field cannot be deleted.")
    group = formobj.parent_of(doc, xref) if not formobj.has_own_name(doc, xref) else None
    page.delete_widget(widget)
    if group is None:
        return
    kids, holder = formobj.array_refs(doc, group, "Kids")
    remaining = [kid for kid in kids if kid != xref]
    if remaining:
        formobj.write_array(doc, group, "Kids", remaining, holder)
    else:
        formobj.replace_in_container(doc, group, None)
