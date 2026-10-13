"""Standard PDF annotations (comments, markup, drawings, shapes)."""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf as fitz

from .geometry import color_to_hex, from_display_point, from_display_rect, hex_to_rgb, to_display_rect

MARKUP = {"highlight", "underline", "strikeout", "squiggly"}
SHAPES = {"rect", "ellipse", "line", "arrow"}
SKIP_TYPES = {fitz.PDF_ANNOT_WIDGET, fitz.PDF_ANNOT_POPUP, fitz.PDF_ANNOT_LINK}
VERTEX_TYPES = {fitz.PDF_ANNOT_INK, fitz.PDF_ANNOT_LINE, fitz.PDF_ANNOT_POLYGON, fitz.PDF_ANNOT_POLY_LINE}


class AnnotationError(ValueError):
    pass


@dataclass(frozen=True)
class AnnotStyle:
    color: str | None = "#ffd400"
    fill: str | None = None
    opacity: float = 1.0
    width: float = 1.5
    dashed: bool = False
    contents: str = ""
    author: str = ""


def _apply_style(annot: fitz.Annot, style: AnnotStyle, allow_fill: bool) -> None:
    colors: dict = {}
    if style.color:
        colors["stroke"] = hex_to_rgb(style.color)
    if allow_fill:
        colors["fill"] = hex_to_rgb(style.fill) if style.fill else None
    if colors:
        annot.set_colors(**colors)
    annot.set_opacity(max(0.05, min(1.0, style.opacity)))
    if annot.type[0] not in (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_TEXT):
        border: dict = {"width": max(0.0, style.width)}
        if style.dashed:
            border["dashes"] = [4, 3]
        annot.set_border(**border)
    info = {}
    if style.contents:
        info["content"] = style.contents
    if style.author:
        info["title"] = style.author
    if info:
        annot.set_info(**info)
    annot.update()


def _quads(page: fitz.Page, rects: list[tuple]) -> list[fitz.Quad]:
    return [from_display_rect(page, r).quad for r in rects if len(r) == 4]


def add_markup(page: fitz.Page, kind: str, rects: list[tuple], style: AnnotStyle) -> int:
    if kind not in MARKUP:
        raise AnnotationError(f"Unknown markup type {kind}")
    quads = _quads(page, rects)
    if not quads:
        raise AnnotationError("Select some text first.")
    adder = {
        "highlight": page.add_highlight_annot,
        "underline": page.add_underline_annot,
        "strikeout": page.add_strikeout_annot,
        "squiggly": page.add_squiggly_annot,
    }[kind]
    annot = adder(quads=quads)
    _apply_style(annot, style, allow_fill=False)
    return annot.xref


def add_ink(page: fitz.Page, paths: list[list[tuple[float, float]]], style: AnnotStyle) -> int:
    converted = [
        [tuple(from_display_point(page, (p[0], p[1]))) for p in path if len(p) >= 2]
        for path in paths
    ]
    converted = [path for path in converted if len(path) >= 2]
    if not converted:
        raise AnnotationError("Drawing is empty.")
    annot = page.add_ink_annot(converted)
    _apply_style(annot, style, allow_fill=False)
    return annot.xref


def add_shape(page: fitz.Page, kind: str, start: tuple, end: tuple, style: AnnotStyle) -> int:
    if kind not in SHAPES:
        raise AnnotationError(f"Unknown shape {kind}")
    p1, p2 = from_display_point(page, start), from_display_point(page, end)
    if kind in ("line", "arrow"):
        if abs(p1 - p2) < 1:
            raise AnnotationError("Line is too short.")
        annot = page.add_line_annot(p1, p2)
        if kind == "arrow":
            annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_OPEN_ARROW)
        _apply_style(annot, style, allow_fill=kind == "arrow")
        return annot.xref
    rect = fitz.Rect(p1, p2)
    rect.normalize()
    if rect.width < 2 or rect.height < 2:
        raise AnnotationError("Shape is too small.")
    annot = page.add_rect_annot(rect) if kind == "rect" else page.add_circle_annot(rect)
    _apply_style(annot, style, allow_fill=True)
    return annot.xref


def add_note(page: fitz.Page, point: tuple, style: AnnotStyle, icon: str = "Comment") -> int:
    annot = page.add_text_annot(from_display_point(page, point), style.contents or "", icon=icon)
    _apply_style(annot, style, allow_fill=False)
    return annot.xref


def add_textbox(page: fitz.Page, rect: tuple, text: str, size: float, style: AnnotStyle, text_color: str) -> int:
    target = from_display_rect(page, rect)
    if target.width < 5 or target.height < 5:
        raise AnnotationError("Text box is too small.")
    annot = page.add_freetext_annot(
        target,
        text,
        fontsize=max(4.0, min(144.0, size)),
        fontname="helv",
        text_color=hex_to_rgb(text_color),
        fill_color=hex_to_rgb(style.fill) if style.fill else None,
        border_width=style.width if style.color else 0,
        rotate=page.rotation,
    )
    annot.set_opacity(max(0.05, min(1.0, style.opacity)))
    annot.update()
    return annot.xref


def _find(page: fitz.Page, xref: int) -> fitz.Annot:
    annot = page.load_annot(xref) if xref else None
    if annot is None:
        raise AnnotationError("Annotation not found (it may have been removed).")
    return annot


def list_annotations(page: fitz.Page) -> list[dict]:
    items = []
    for annot in page.annots() or []:
        kind = annot.type[0]
        if kind in SKIP_TYPES:
            continue
        colors = annot.colors or {}
        info = annot.info or {}
        items.append({
            "xref": annot.xref,
            "type": annot.type[1],
            "rect": to_display_rect(page, annot.rect),
            "color": color_to_hex(colors["stroke"]) if colors.get("stroke") else None,
            "fill": color_to_hex(colors["fill"]) if colors.get("fill") else None,
            "opacity": round(annot.opacity if annot.opacity >= 0 else 1.0, 3),
            "width": (annot.border or {}).get("width", 1) or 0,
            "contents": info.get("content", ""),
            "author": info.get("title", ""),
            "modified": info.get("modDate", ""),
        })
    return items


def update_annotation(page: fitz.Page, xref: int, style: AnnotStyle, rect: tuple | None) -> int:
    annot = _find(page, xref)
    if rect is not None:
        annot = _move(page, annot, from_display_rect(page, rect))
    allow_fill = annot.type[0] in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE, fitz.PDF_ANNOT_FREE_TEXT, fitz.PDF_ANNOT_LINE)
    if annot.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
        annot.set_opacity(max(0.05, min(1.0, style.opacity)))
        if style.contents:
            annot.set_info(content=style.contents)
        annot.update(text_color=hex_to_rgb(style.color) if style.color else None,
                     fill_color=hex_to_rgb(style.fill) if style.fill else None)
        return annot.xref
    _apply_style(annot, style, allow_fill)
    if rect is not None:
        keep_rect(annot, from_display_rect(page, rect))
    return annot.xref


def keep_rect(annot: fitz.Annot, target: fitz.Rect) -> None:
    """MuPDF grows a box annotation's rect to fit its border on update: compensate,
    so moving an annotation never makes it bigger."""
    if annot.type[0] in VERTEX_TYPES:
        return
    grown = fitz.Rect(annot.rect)
    grow = (target.x0 - grown.x0, target.y0 - grown.y0, grown.x1 - target.x1, grown.y1 - target.y1)
    if max(abs(g) for g in grow) < 0.05:
        return
    inner = fitz.Rect(target.x0 + grow[0], target.y0 + grow[1], target.x1 - grow[2], target.y1 - grow[3])
    if inner.is_empty:
        return
    annot.set_rect(inner)
    annot.update()


def _move(page: fitz.Page, annot: fitz.Annot, target: fitz.Rect) -> fitz.Annot:
    kind = annot.type[0]
    if kind not in VERTEX_TYPES:
        annot.set_rect(target)
        annot.update()
        return annot
    source = fitz.Rect(annot.rect)
    sx = target.width / source.width if source.width else 1.0
    sy = target.height / source.height if source.height else 1.0

    def transform(point: tuple) -> tuple[float, float]:
        return (target.x0 + (point[0] - source.x0) * sx, target.y0 + (point[1] - source.y0) * sy)

    vertices = annot.vertices or []
    if kind == fitz.PDF_ANNOT_INK:
        return _recreate_ink(page, annot, [[transform(p) for p in stroke] for stroke in vertices])
    if kind == fitz.PDF_ANNOT_LINE and len(vertices) >= 2:
        return _recreate_line(page, annot, transform(vertices[0]), transform(vertices[1]))
    annot.set_vertices([transform(p) for p in vertices])
    annot.update()
    return annot


def _copy_props(source: fitz.Annot, target: fitz.Annot) -> None:
    colors = source.colors or {}
    target.set_colors(stroke=colors.get("stroke"), fill=colors.get("fill"))
    target.set_opacity(source.opacity if source.opacity >= 0 else 1.0)
    border = source.border or {}
    target.set_border(width=border.get("width", 1) or 1, dashes=border.get("dashes") or None)
    target.set_info(source.info)


def _recreate_ink(page: fitz.Page, annot: fitz.Annot, strokes: list) -> fitz.Annot:
    new = page.add_ink_annot(strokes)
    _copy_props(annot, new)
    page.delete_annot(annot)
    new.update()
    return new


def _recreate_line(page: fitz.Page, annot: fitz.Annot, p1: tuple, p2: tuple) -> fitz.Annot:
    line_ends = annot.line_ends
    new = page.add_line_annot(p1, p2)
    _copy_props(annot, new)
    if line_ends:
        new.set_line_ends(*line_ends)
    page.delete_annot(annot)
    new.update()
    return new


def delete_annotation(page: fitz.Page, xref: int) -> None:
    page.delete_annot(_find(page, xref))
