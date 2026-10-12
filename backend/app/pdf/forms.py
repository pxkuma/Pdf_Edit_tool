"""Interactive form (AcroForm) fields: list, fill, create, remove."""

from __future__ import annotations

import pymupdf as fitz

from .geometry import from_display_rect, to_display_rect

FIELD_TYPES = {
    fitz.PDF_WIDGET_TYPE_TEXT: "text",
    fitz.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    fitz.PDF_WIDGET_TYPE_COMBOBOX: "combobox",
    fitz.PDF_WIDGET_TYPE_LISTBOX: "listbox",
    fitz.PDF_WIDGET_TYPE_SIGNATURE: "signature",
    fitz.PDF_WIDGET_TYPE_BUTTON: "button",
}
NEW_FIELD_TYPES = {"text": fitz.PDF_WIDGET_TYPE_TEXT, "checkbox": fitz.PDF_WIDGET_TYPE_CHECKBOX}


class FormError(ValueError):
    pass


def list_fields(doc: fitz.Document) -> list[dict]:
    fields = []
    for page in doc:
        fields.extend(list_fields_on_page(page))
    return fields


def list_fields_on_page(page: fitz.Page) -> list[dict]:
    fields = []
    for widget in page.widgets() or []:
        kind = FIELD_TYPES.get(widget.field_type, "unknown")
        fields.append({
            "xref": widget.xref,
            "page": page.number,
            "name": widget.field_name or f"field_{widget.xref}",
            "label": widget.field_label or "",
            "type": kind,
            "value": _value(widget, kind),
            "options": list(widget.choice_values or []) if kind in ("combobox", "listbox") else [],
            "onState": _on_state(widget) if kind in ("checkbox", "radio") else None,
            "rect": to_display_rect(page, widget.rect),
            "readOnly": bool(widget.field_flags & fitz.PDF_FIELD_IS_READ_ONLY),
            "required": bool(widget.field_flags & fitz.PDF_FIELD_IS_REQUIRED),
            "multiline": bool(widget.field_flags & fitz.PDF_TX_FIELD_IS_MULTILINE) if kind == "text" else False,
            "maxLength": widget.text_maxlen or 0,
        })
    return fields


def _on_state(widget: fitz.Widget) -> str:
    try:
        state = widget.on_state()
    except Exception:  # noqa: BLE001
        state = "Yes"
    return state if isinstance(state, str) and state else "Yes"


def _value(widget: fitz.Widget, kind: str):
    value = widget.field_value
    if kind in ("checkbox", "radio"):
        return value not in (None, "", "Off", False)
    return "" if value is None else value


def _find_widget(doc: fitz.Document, page_index: int, xref: int) -> tuple[fitz.Page, fitz.Widget]:
    if not 0 <= page_index < doc.page_count:
        raise FormError("Page out of range.")
    page = doc[page_index]
    for widget in page.widgets() or []:
        if widget.xref == xref:
            return page, widget
    raise FormError("Form field not found.")


def set_values(doc: fitz.Document, values: list[dict]) -> set[int]:
    changed: set[int] = set()
    for item in values:
        page, widget = _find_widget(doc, int(item["page"]), int(item["xref"]))
        if widget.field_flags & fitz.PDF_FIELD_IS_READ_ONLY:
            continue
        kind = FIELD_TYPES.get(widget.field_type, "unknown")
        value = item.get("value")
        if kind in ("checkbox", "radio"):
            widget.field_value = _on_state(widget) if value else "Off"
        elif kind in ("combobox", "listbox", "text"):
            text = "" if value is None else str(value)
            if widget.text_maxlen and len(text) > widget.text_maxlen:
                text = text[: widget.text_maxlen]
            widget.field_value = text
        else:
            continue
        widget.update()
        changed.add(page.number)
    return changed


def add_field(page: fitz.Page, kind: str, rect: tuple, name: str, value: str | bool | None) -> int:
    if kind not in NEW_FIELD_TYPES:
        raise FormError("Only text fields and checkboxes can be created.")
    target = from_display_rect(page, rect)
    if target.width < 6 or target.height < 6:
        raise FormError("Field area is too small.")
    widget = fitz.Widget()
    widget.field_type = NEW_FIELD_TYPES[kind]
    widget.field_name = (name or f"{kind}_{page.number + 1}").strip()[:120]
    widget.rect = target
    widget.text_fontsize = 0
    widget.border_color = (0.45, 0.45, 0.55)
    widget.border_width = 0.8
    if kind == "text":
        widget.field_value = str(value or "")
    else:
        widget.field_value = bool(value)
    annot = page.add_widget(widget)
    return annot.xref


def delete_field(doc: fitz.Document, page_index: int, xref: int) -> None:
    page, widget = _find_widget(doc, page_index, xref)
    page.delete_widget(widget)
