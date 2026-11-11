"""Export the comments of a document as XFDF, the XML form of Acrobat's comment files."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pymupdf as fitz

from .comments import MARKUP_SUBTYPES, Entry, collect
from .geometry import color_to_hex
from .pdfdates import format_pdf_date, parse_pdf_date
from .xfdf_space import PageSpace, number_text

NS = "http://ns.adobe.com/xfdf/"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

TAGS = {
    "Text": "text", "Highlight": "highlight", "Underline": "underline", "StrikeOut": "strikeout",
    "Squiggly": "squiggly", "FreeText": "freetext", "Ink": "ink", "Line": "line", "Square": "square",
    "Circle": "circle", "Polygon": "polygon", "PolyLine": "polyline", "Caret": "caret", "Stamp": "stamp",
}
FLAG_NAMES = (
    (1, "invisible"), (2, "hidden"), (4, "print"), (8, "nozoom"), (16, "norotate"), (32, "noview"),
    (64, "readonly"), (128, "locked"), (256, "togglenoview"), (512, "lockedcontents"),
)
LINE_ENDS = ("None", "Square", "Circle", "Diamond", "OpenArrow", "ClosedArrow", "Butt", "ROpenArrow",
             "RClosedArrow", "Slash")
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_WITH_WIDTH = {"Ink", "Line", "Square", "Circle", "Polygon", "PolyLine", "FreeText"}


def _clean(text: str) -> str:
    return _XML_ILLEGAL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def flag_names(flags: int) -> str:
    return ",".join(name for bit, name in FLAG_NAMES if flags & bit)


def _date(raw: str) -> str:
    moment = parse_pdf_date(raw)
    return format_pdf_date(moment) if moment else ""


def _key(entry: Entry, key: str) -> tuple[str, str]:
    return entry.annot.parent.parent.xref_get_key(entry.xref, key)


def _rect_text(entry: Entry, space: PageSpace) -> str:
    """The annotation's ``/Rect`` as written in the file (already PDF user space).

    MuPDF's own rectangle differs from it for annotations that do not rotate with the page, such as
    notes on a rotated page, so the file's value is the one XFDF must carry.
    """
    kind, value = _key(entry, "Rect")
    parts = value.strip("[] ").split() if kind == "array" else []
    try:
        x0, y0, x1, y1 = (float(v) for v in parts)
    except ValueError:
        return space.pdf_rect_text(entry.annot.rect)
    return ",".join(number_text(v) for v in (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))


def _common(entry: Entry, space: PageSpace) -> dict[str, str]:
    annot, info = entry.annot, entry.info
    attrs = {
        "name": entry.name,
        "page": str(entry.page),
        "rect": _rect_text(entry, space),
        "flags": flag_names(annot.flags),
        "title": info.get("title", ""),
        "subject": info.get("subject", ""),
        "date": _date(info.get("modDate", "")),
        "creationdate": _date(info.get("creationDate", "")),
    }
    colors = annot.colors or {}
    if colors.get("stroke"):
        attrs["color"] = color_to_hex(colors["stroke"]).upper()
    if annot.opacity >= 0 and annot.opacity != 1:
        attrs["opacity"] = number_text(annot.opacity)
    if entry.parent is not None:
        kind, value = _key(entry, "RT")
        attrs["inreplyto"] = entry.parent.name
        attrs["replyType"] = "Group" if (kind, value) == ("name", "/Group") else "R"
    if entry.state:
        attrs.update(state=entry.state, statemodel=entry.state_model)
    return attrs


def _specific(entry: Entry, space: PageSpace, node: ET.Element) -> dict[str, str]:
    annot, subtype = entry.annot, entry.subtype
    colors, attrs = annot.colors or {}, {}
    width = (annot.border or {}).get("width")
    if subtype in _WITH_WIDTH and width is not None:
        attrs["width"] = number_text(width)
    if subtype != "FreeText" and colors.get("fill"):
        attrs["interior-color"] = color_to_hex(colors["fill"]).upper()
    points = annot.vertices or []
    if subtype == "Text":
        attrs["icon"] = entry.info.get("name", "") or "Note"
    elif subtype in MARKUP_SUBTYPES:
        attrs["coords"] = ",".join(number_text(v) for p in points for v in space.pdf_point(p))
    elif subtype == "Line" and len(points) >= 2:
        head, tail = annot.line_ends or (0, 0)
        attrs.update(start=space.pdf_point_text(points[0]), end=space.pdf_point_text(points[1]),
                     head=LINE_ENDS[head % len(LINE_ENDS)], tail=LINE_ENDS[tail % len(LINE_ENDS)])
    elif subtype == "Ink":
        ink = ET.SubElement(node, "inklist")
        for stroke in points:
            ET.SubElement(ink, "gesture").text = space.pdf_points_text(stroke)
    elif subtype in ("Polygon", "PolyLine"):
        ET.SubElement(node, "vertices").text = space.pdf_points_text(points)
    elif subtype == "FreeText":
        kind, value = _key(entry, "DA")
        if kind == "string" and value:
            ET.SubElement(node, "defaultappearance").text = _clean(value)
    return attrs


def _entry_node(entry: Entry, space: PageSpace) -> ET.Element:
    node = ET.Element(TAGS[entry.subtype])
    attrs = {**_common(entry, space), **_specific(entry, space, node)}
    for key in sorted(attrs):
        if attrs[key] != "":
            node.set(key, _clean(attrs[key]))
    contents = entry.info.get("content", "")
    if contents:
        ET.SubElement(node, "contents").text = _clean(contents)
    return node


def _threads(entries: list[Entry]) -> list[Entry]:
    """Every entry once, each comment followed by its states and replies (parents before children)."""
    result: list[Entry] = []

    def visit(entry: Entry) -> None:
        result.append(entry)
        for child in entry.children:
            visit(child)

    for entry in entries:
        if entry.parent is None:
            visit(entry)
    return result


def export_xfdf(doc: fitz.Document, filename: str = "") -> bytes:
    """All comments, replies and review states of ``doc`` as an XFDF document (UTF-8)."""
    root = ET.Element("xfdf", {"xmlns": NS, XML_SPACE: "preserve"})
    if filename:
        ET.SubElement(root, "f", {"href": _clean(filename)})
    annots = ET.SubElement(root, "annots")
    spaces: dict[int, PageSpace] = {}
    for entry in _threads(collect(doc)):
        space = spaces.setdefault(entry.page, PageSpace(entry.sheet))
        annots.append(_entry_node(entry, space))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
