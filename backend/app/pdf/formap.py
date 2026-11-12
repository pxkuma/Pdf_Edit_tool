"""Appearance streams (/AP) MuPDF does not draw the way other viewers expect.

MuPDF draws good appearances for text fields, checkboxes, radio buttons and push buttons. Three cases are
written here instead, so every viewer shows the same thing without regenerating anything:

* list boxes: the selected options are highlighted (MuPDF draws the list without the selection);
* dropdowns whose options have a display label different from the export value: the label is shown;
* empty signature fields: a plain box (MuPDF draws an orange "SIGN" marker).
"""

from __future__ import annotations

import pymupdf as fitz

from .formobj import STANDARD_FONTS, pdf_strings
from .pdfobj import get_key, read_number_array

HIGHLIGHT = (0.6, 0.75, 0.85)
SIGN_FILL = (0.94, 0.96, 1.0)
LIST_AUTO_SIZE = 12.0
_FITZ_FONT = {"Helv": "helv", "HeBo": "hebo", "TiRo": "tiro", "TiBo": "tibo", "Cour": "cour", "CoBo": "cobo"}


def _num(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def _rgb(color: list[float] | tuple | None) -> tuple[float, float, float] | None:
    if not color:
        return None
    values = list(color)
    if len(values) == 1:
        return (values[0],) * 3  # type: ignore[return-value]
    if len(values) == 4:
        c, m, y, k = values
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return (values[0], values[1], values[2])


def _pdf_text(text: str) -> str:
    raw = text.encode("cp1252", errors="replace").decode("latin-1")
    return "(" + raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def _frame(width: float, height: float, fill, border, border_width: float) -> list[str]:
    ops = []
    if fill:
        ops.append(f"{_num(fill[0])} {_num(fill[1])} {_num(fill[2])} rg 0 0 {_num(width)} {_num(height)} re f")
    if border and border_width > 0:
        half = border_width / 2
        ops.append(
            f"{_num(border[0])} {_num(border[1])} {_num(border[2])} RG {_num(border_width)} w "
            f"{_num(half)} {_num(half)} {_num(width - border_width)} {_num(height - border_width)} re S"
        )
    return ops


def _install(doc: fitz.Document, widget_xref: int, width: float, height: float, content: str, font: str | None) -> None:
    resources = ""
    if font:
        base = STANDARD_FONTS.get(font, "Helvetica")
        resources = f"/Resources<</Font<</{font}<</Type/Font/Subtype/Type1/BaseFont/{base}/Encoding/WinAnsiEncoding>>>>>>"
    stream = doc.get_new_xref()
    doc.update_object(stream, f"<</Type/XObject/Subtype/Form/BBox[0 0 {_num(width)} {_num(height)}]{resources}>>")
    doc.update_stream(stream, content.encode("latin-1"))
    doc.xref_set_key(widget_xref, "AP", f"<</N {stream} 0 R>>")


def _box(doc: fitz.Document, widget: fitz.Widget) -> tuple[float, float]:
    rect = read_number_array(doc, widget.xref, "Rect")
    if len(rect) == 4:
        return abs(rect[2] - rect[0]), abs(rect[3] - rect[1])
    return widget.rect.width, widget.rect.height


def _font(widget: fitz.Widget) -> str:
    return widget.text_font if widget.text_font in _FITZ_FONT else "Helv"


def _alignment(doc: fitz.Document, xref: int) -> int:
    kind, value = get_key(doc, xref, "Q")
    return int(value) if kind == "int" and value in ("0", "1", "2") else 0


def _text_x(text: str, font: str, size: float, width: float, inset: float, align: int) -> float:
    length = fitz.get_text_length(text, fontname=_FITZ_FONT[font], fontsize=size)
    if align == 1:
        return max(inset, (width - length) / 2)
    if align == 2:
        return max(inset, width - inset - length)
    return inset


def choice_labels(widget: fitz.Widget) -> list[tuple[str, str]]:
    """(export value, display label) of every option."""
    pairs = []
    for option in widget.choice_values or []:
        if isinstance(option, (list, tuple)) and len(option) >= 2:
            pairs.append((str(option[0]), str(option[1])))
        else:
            pairs.append((str(option), str(option)))
    return pairs


def selected_values(doc: fitz.Document, head: int) -> list[str]:
    kind, value = get_key(doc, head, "V")
    if kind == "string":
        return [value]
    if kind == "array":
        return pdf_strings(value)
    return []


def draw_listbox(doc: fitz.Document, widget: fitz.Widget, selected: list[str]) -> None:
    width, height = _box(doc, widget)
    font = _font(widget)
    size = widget.text_fontsize or LIST_AUTO_SIZE
    color = _rgb(widget.text_color) or (0, 0, 0)
    border_width = widget.border_width if widget.border_color else 0
    inset = border_width + 2
    line = size * 1.15
    ops = ["/Tx BMC q", *_frame(width, height, _rgb(widget.fill_color), _rgb(widget.border_color), border_width)]
    ops.append(f"{_num(border_width)} {_num(border_width)} {_num(width - 2 * border_width)} {_num(height - 2 * border_width)} re W n")
    align = _alignment(doc, widget.xref)
    top = height - border_width
    for index, (value, label) in enumerate(choice_labels(widget)):
        y1 = top - index * line
        if y1 - line < -line:
            break
        if value in selected:
            ops.append(f"{_num(HIGHLIGHT[0])} {_num(HIGHLIGHT[1])} {_num(HIGHLIGHT[2])} rg "
                       f"{_num(border_width)} {_num(y1 - line)} {_num(width - 2 * border_width)} {_num(line)} re f")
        x = _text_x(label, font, size, width, inset, align)
        baseline = y1 - line + (line - size) / 2 + size * 0.22
        ops.append(f"BT /{font} {_num(size)} Tf {_num(color[0])} {_num(color[1])} {_num(color[2])} rg "
                   f"{_num(x)} {_num(baseline)} Td {_pdf_text(label)} Tj ET")
    ops.append("Q EMC")
    _install(doc, widget.xref, width, height, "\n".join(ops), font)


def draw_combobox(doc: fitz.Document, widget: fitz.Widget, value: str) -> None:
    width, height = _box(doc, widget)
    labels = dict(choice_labels(widget))
    text = labels.get(value, value)
    font = _font(widget)
    border_width = widget.border_width if widget.border_color else 0
    size = widget.text_fontsize or max(4.0, min(LIST_AUTO_SIZE, (height - 2 * border_width - 2) / 1.15))
    color = _rgb(widget.text_color) or (0, 0, 0)
    inset = border_width + 2
    ops = ["/Tx BMC q", *_frame(width, height, _rgb(widget.fill_color), _rgb(widget.border_color), border_width)]
    ops.append(f"{_num(border_width)} {_num(border_width)} {_num(width - 2 * border_width)} {_num(height - 2 * border_width)} re W n")
    if text:
        x = _text_x(text, font, size, width, inset, _alignment(doc, widget.xref))
        baseline = (height - size) / 2 + size * 0.22
        ops.append(f"BT /{font} {_num(size)} Tf {_num(color[0])} {_num(color[1])} {_num(color[2])} rg "
                   f"{_num(x)} {_num(baseline)} Td {_pdf_text(text)} Tj ET")
    ops.append("Q EMC")
    _install(doc, widget.xref, width, height, "\n".join(ops), font)


def draw_empty_signature(doc: fitz.Document, widget: fitz.Widget) -> None:
    width, height = _box(doc, widget)
    fill = _rgb(widget.fill_color) or SIGN_FILL
    border_width = widget.border_width if widget.border_color else 0
    ops = ["q", *_frame(width, height, fill, _rgb(widget.border_color), border_width), "Q"]
    _install(doc, widget.xref, width, height, "\n".join(ops), None)
