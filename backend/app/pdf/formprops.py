"""Field properties: read them for the properties panel, and apply edits (name, tooltip, flags, appearance...).

Group-level properties (name, tooltip, required, read-only, default value) live on the field; for a radio
group that is the parent of the buttons. Appearance and position belong to the selected widget, as in
Acrobat.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf as fitz

from . import formap, formobj
from .formerror import FormError
from .formformat import FieldFormat, coerce_value, parse_format, scripts_for
from .formnames import check_rename
from .geometry import Rect4, color_to_hex, from_display_rect, hex_to_rgb
from .pdfobj import get_key

FONTS = {"Helvetica": "Helv", "Times": "TiRo", "Courier": "Cour"}
FONT_NAMES = {code: name for name, code in FONTS.items()}
BORDER_STYLES = {"solid": "S", "dashed": "D", "beveled": "B", "inset": "I", "underline": "U"}
ALIGNMENTS = ("left", "center", "right")
ACTIONS = ("none", "reset", "print", "url", "submit")
MIN_FIELD = 6.0
MAX_OPTIONS = 500

FLAG_READ_ONLY = fitz.PDF_FIELD_IS_READ_ONLY
FLAG_REQUIRED = fitz.PDF_FIELD_IS_REQUIRED
FLAG_MULTILINE = fitz.PDF_TX_FIELD_IS_MULTILINE
FLAG_COMB = fitz.PDF_TX_FIELD_IS_COMB
FLAG_EDIT = fitz.PDF_CH_FIELD_IS_EDIT
FLAG_MULTI_SELECT = fitz.PDF_CH_FIELD_IS_MULTI_SELECT
FLAG_NO_TOGGLE_OFF = 1 << 14  # PDF_BTN_FIELD_NO_TOGGLE_TO_OFF (not exported by PyMuPDF)


@dataclass(frozen=True)
class FieldProps:
    """A property edit; ``None`` keeps what the field has."""

    name: str | None = None
    tooltip: str | None = None
    required: bool | None = None
    read_only: bool | None = None
    default_value: str | bool | tuple[str, ...] | None = None
    font: str | None = None
    font_size: float | None = None  # 0 = auto size
    text_color: str | None = None
    fill_color: str | None = None  # "#rrggbb" or "none"
    border_color: str | None = None  # "#rrggbb" or "none"
    border_width: float | None = None
    border_style: str | None = None
    align: str | None = None
    multiline: bool | None = None
    max_length: int | None = None  # 0 = no limit
    comb: bool | None = None
    format: FieldFormat | None = None
    options: tuple[tuple[str, str], ...] | None = None  # (export value, display label)
    editable: bool | None = None
    multi_select: bool | None = None
    export_value: str | None = None
    caption: str | None = None
    action: str | None = None
    url: str | None = None
    rect: Rect4 | None = None  # display space


# ------------------------------------------------------------------ reading
def _color(value) -> str | None:
    return color_to_hex(value) if value else None


def _align(doc: fitz.Document, xref: int, head: int) -> str:
    for target in (xref, head):
        kind, value = get_key(doc, target, "Q")
        if kind == "int" and value in ("0", "1", "2"):
            return ALIGNMENTS[int(value)]
    return "left"


def _default_value(doc: fitz.Document, head: int):
    kind, value = get_key(doc, head, "DV")
    if kind == "string":
        return value
    if kind == "name":
        return "" if value == "/Off" else value.lstrip("/")
    if kind == "array":
        return formobj.pdf_strings(value)
    return ""


def read_action(doc: fitz.Document, xref: int) -> tuple[str, str]:
    kind, value = get_key(doc, xref, "A/S")
    if kind != "name":
        return "none", ""
    if value == "/ResetForm":
        return "reset", ""
    if value == "/Named" and get_key(doc, xref, "A/N")[1] == "/Print":
        return "print", ""
    if value == "/URI":
        return "url", get_key(doc, xref, "A/URI")[1]
    if value == "/SubmitForm":
        target = get_key(doc, xref, "A/F/F")
        return "submit", target[1] if target[0] == "string" else get_key(doc, xref, "A/F")[1]
    return "other", ""


def read_props(doc: fitz.Document, widget: fitz.Widget, kind: str) -> dict:
    head = formobj.field_head(doc, widget.xref)
    flags = widget.field_flags or 0
    action, url = read_action(doc, widget.xref) if kind == "button" else ("none", "")
    choices = [{"value": v, "label": label} for v, label in formap.choice_labels(widget)] if kind in ("combobox", "listbox") else []
    return {
        "tooltip": widget.field_label or "",
        "defaultValue": _default_value(doc, head),
        "font": FONT_NAMES.get(widget.text_font, widget.text_font or "Helvetica"),
        "fontSize": float(widget.text_fontsize or 0),
        "textColor": color_to_hex(widget.text_color or (0, 0, 0)),
        "fillColor": _color(widget.fill_color),
        "borderColor": _color(widget.border_color),
        "borderWidth": float(widget.border_width or 0) if widget.border_color else 0.0,
        "borderStyle": next((k for k, v in BORDER_STYLES.items() if (widget.border_style or "S")[:1].upper() == v), "solid"),
        "align": _align(doc, widget.xref, head),
        "comb": bool(flags & FLAG_COMB) if kind == "text" else False,
        "format": parse_format(widget.script_format).to_json() if kind == "text" else FieldFormat().to_json(),
        "choices": choices,
        "editable": bool(flags & FLAG_EDIT) if kind == "combobox" else False,
        "multiSelect": bool(flags & FLAG_MULTI_SELECT) if kind == "listbox" else False,
        "caption": widget.button_caption or "" if kind == "button" else "",
        "action": action,
        "url": url,
        "group": len(formobj.kids_of(doc, head)) if kind == "radio" and head != widget.xref else (1 if kind == "radio" else 0),
        "signed": bool(widget.is_signed) if kind == "signature" else False,
    }


# ------------------------------------------------------------------ writing
def _flags(widget: fitz.Widget, kind: str, props: FieldProps) -> int:
    flags = widget.field_flags or 0

    def toggle(flag: int, value: bool | None) -> None:
        nonlocal flags
        if value is not None:
            flags = flags | flag if value else flags & ~flag

    toggle(FLAG_READ_ONLY, props.read_only)
    toggle(FLAG_REQUIRED, props.required)
    if kind == "text":
        toggle(FLAG_MULTILINE, props.multiline)
        toggle(FLAG_COMB, props.comb)
        if flags & FLAG_COMB and (flags & FLAG_MULTILINE or not _max_length(widget, props)):
            raise FormError("A comb field needs a maximum length and cannot be multi-line.")
    elif kind == "combobox":
        toggle(FLAG_EDIT, props.editable)
    elif kind == "listbox":
        toggle(FLAG_MULTI_SELECT, props.multi_select)
    elif kind == "radio":
        flags |= FLAG_NO_TOGGLE_OFF
    return flags


def _max_length(widget: fitz.Widget, props: FieldProps) -> int:
    return props.max_length if props.max_length is not None else (widget.text_maxlen or 0)


def _color_value(value: str) -> tuple[float, float, float] | None:
    return None if value == "none" else hex_to_rgb(value)


def _set_rect(page: fitz.Page, widget: fitz.Widget, rect: Rect4) -> None:
    target = from_display_rect(page, rect)
    if target.width < MIN_FIELD or target.height < MIN_FIELD:
        raise FormError("Field area is too small.")
    if not target.intersects(page.rect):
        raise FormError("The field must stay on the page.")
    widget.rect = target


def _set_appearance(widget: fitz.Widget, props: FieldProps) -> None:
    if props.font is not None:
        if props.font not in FONTS:
            raise FormError("Unknown font. Use Helvetica, Times or Courier.")
        widget.text_font = FONTS[props.font]
    if props.font_size is not None:
        widget.text_fontsize = props.font_size
    if props.text_color is not None:
        widget.text_color = hex_to_rgb(props.text_color)
    if props.fill_color is not None:
        widget.fill_color = _color_value(props.fill_color)
    if props.border_color is not None:
        widget.border_color = _color_value(props.border_color)
    if props.border_width is not None:
        widget.border_width = props.border_width
    if props.border_style is not None:
        widget.border_style = BORDER_STYLES[props.border_style]
        widget.border_dashes = [3] if props.border_style == "dashed" else None


def _set_content(widget: fitz.Widget, kind: str, props: FieldProps) -> None:
    if props.tooltip is not None:
        widget.field_label = props.tooltip
    if kind == "text":
        if props.max_length is not None:
            widget.text_maxlen = props.max_length
        if props.format is not None:
            widget.script_stroke, widget.script_format = scripts_for(props.format)
    if kind in ("combobox", "listbox") and props.options is not None:
        if len(props.options) > MAX_OPTIONS:
            raise FormError(f"A list can hold at most {MAX_OPTIONS} options.")
        values = [value for value, _label in props.options]
        if len(set(values)) != len(values):
            raise FormError("Each option needs a different export value.")
        widget.choice_values = [value if value == label else [value, label] for value, label in props.options]
    if kind == "button" and props.caption is not None:
        widget.button_caption = props.caption


def _prepare_raw(doc: fitz.Document, widget: fitz.Widget, props: FieldProps) -> None:
    """Raw keys MuPDF reads when it draws the appearance, written before ``widget.update()``."""
    if props.align is not None:
        doc.xref_set_key(widget.xref, "Q", str(ALIGNMENTS.index(props.align)))
    if props.fill_color == "none":
        formobj.del_key(doc, widget.xref, "MK/BG")
    if props.border_color == "none":
        formobj.del_key(doc, widget.xref, "MK/BC")
        doc.xref_set_key(widget.xref, "BS/W", "0")
    if props.max_length == 0:
        formobj.del_key(doc, widget.xref, "MaxLen")
    if props.border_style is not None and props.border_style != "dashed":
        formobj.del_key(doc, widget.xref, "BS/D")


def _write_action(doc: fitz.Document, xref: int, action: str, url: str | None) -> None:
    if action == "none":
        formobj.del_key(doc, xref, "A")
    elif action == "reset":
        doc.xref_set_key(xref, "A", "<</S/ResetForm>>")
    elif action == "print":
        doc.xref_set_key(xref, "A", "<</S/Named/N/Print>>")
    elif action in ("url", "submit"):
        if not url:
            raise FormError("Enter the web address for this button.")
        target = fitz.get_pdf_str(url)
        value = f"<</S/URI/URI{target}>>" if action == "url" else f"<</S/SubmitForm/F<</FS/URL/F{target}>>/Flags 4>>"
        doc.xref_set_key(xref, "A", value)


def _default_token(kind: str, value, export: str) -> str:
    if kind == "checkbox":
        return formobj.pdf_name(export) if value in (True, "true", export) else "/Off"
    if kind == "radio":
        return formobj.pdf_name(str(value)) if value not in (None, "", False, "Off") else "/Off"
    if isinstance(value, tuple):
        return "[" + "".join(fitz.get_pdf_str(item) for item in value) + "]"
    return fitz.get_pdf_str(str(value))


def _write_field_level(doc: fitz.Document, widget: fitz.Widget, kind: str, props: FieldProps, flags: int) -> None:
    head = formobj.field_head(doc, widget.xref)
    if props.name is not None:
        clean = check_rename(doc, head, props.name)
        doc.xref_set_key(head, "T", fitz.get_pdf_str(clean))
    if head != widget.xref:
        for target in (head, *formobj.kids_of(doc, head)):  # PyMuPDF writes /Ff on each kid it updates
            doc.xref_set_key(target, "Ff", str(flags))
        if props.tooltip is not None:
            doc.xref_set_key(head, "TU", fitz.get_pdf_str(props.tooltip))
            formobj.del_key(doc, widget.xref, "TU")
    if props.default_value is not None:
        export = _export_value(doc, widget, kind)
        value = props.default_value
        if kind == "text" and isinstance(value, str):
            value = coerce_value(parse_format(widget.script_format), value)
        doc.xref_set_key(head, "DV", _default_token(kind, value, export))
    if kind == "button" and props.action is not None:
        _write_action(doc, widget.xref, props.action, props.url)


def _export_value(doc: fitz.Document, widget: fitz.Widget, kind: str) -> str:
    if kind not in ("checkbox", "radio"):
        return ""
    states = widget.button_states() or {}
    return next((s for s in (states.get("normal") or []) if s != "Off"), "Yes")


def change_export_value(doc: fitz.Document, widget: fitz.Widget, kind: str, new_value: str) -> None:
    old = _export_value(doc, widget, kind)
    if new_value == old:
        return
    head = formobj.field_head(doc, widget.xref)
    if kind == "radio" and head != widget.xref:
        for kid in formobj.kids_of(doc, head):
            if kid != widget.xref and new_value in _states_of(doc, kid):
                raise FormError(f"Another button of this group already uses the export value “{new_value}”.")
    was_on = get_key(doc, head, "V")[1] == formobj.pdf_name(old)
    formobj.rename_on_state(doc, widget.xref, new_value)
    if was_on:
        formobj.set_name_value(doc, head, new_value)


def _states_of(doc: fitz.Document, xref: int) -> list[str]:
    return [formobj.decode_name(name) for name in formobj.on_state_names(doc, xref)]


def refresh_appearance(doc: fitz.Document, page: fitz.Page, xref: int, kind: str) -> None:
    """Write the appearances MuPDF does not draw like other viewers (see formap)."""
    if kind not in ("listbox", "combobox", "signature"):
        return
    widget = page.load_widget(xref)
    head = formobj.field_head(doc, xref)
    if kind == "listbox":
        formap.draw_listbox(doc, widget, formap.selected_values(doc, head))
    elif kind == "combobox":
        selected = formap.selected_values(doc, head)
        formap.draw_combobox(doc, widget, selected[0] if selected else "")
    elif not widget.is_signed:
        formap.draw_empty_signature(doc, widget)


def apply_props(doc: fitz.Document, page: fitz.Page, widget: fitz.Widget, kind: str, props: FieldProps) -> None:
    if props.rect is not None:
        _set_rect(page, widget, props.rect)
    _set_appearance(widget, props)
    _set_content(widget, kind, props)
    flags = _flags(widget, kind, props)
    widget.field_flags = flags
    if kind == "radio":  # PyMuPDF turns a radio on for any truthy value, including "Off"
        widget.field_value = get_key(doc, widget.xref, "AS")[1] not in ("/Off", "null")
    _prepare_raw(doc, widget, props)
    widget.update()
    if kind == "radio":
        head = formobj.field_head(doc, widget.xref)
        state = get_key(doc, head, "V")
        if state[0] == "string":
            formobj.set_name_value(doc, head, state[1])
    _write_field_level(doc, widget, kind, props, flags)
    if props.export_value is not None and kind in ("checkbox", "radio"):
        change_export_value(doc, widget, kind, props.export_value)
    refresh_appearance(doc, page, widget.xref, kind)
