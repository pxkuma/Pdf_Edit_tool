"""Move the content below an edited text box so a growing box never overlaps it.

The editor sends the exact items to move (text lines, vector graphics, images,
form fields, annotations) and the vertical shift it previewed. Everything is
moved *as itself*, never as a picture:

- text is rewritten with its original font objects and text state (by the
  caller, see ``textedit``); lines that cannot be rewritten exactly are copied
  from a snapshot of the page instead, so they still look identical;
- vector paths are redrawn from ``get_drawings()`` with their colours,
  opacity, dashes, caps and joins;
- images are placed again from the same image object (no re-encoding);
- form fields and box-like annotations get a new rectangle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf as fitz

PAD = 1.5  # tolerance when matching objects to the items the editor sent
MAX_PATHS = 6000  # pages with more vector paths than this are not clustered
_MOVABLE_ANNOTS = {
    fitz.PDF_ANNOT_TEXT, fitz.PDF_ANNOT_FREE_TEXT, fitz.PDF_ANNOT_SQUARE,
    fitz.PDF_ANNOT_CIRCLE, fitz.PDF_ANNOT_STAMP, fitz.PDF_ANNOT_FILE_ATTACHMENT,
}


@dataclass(frozen=True)
class PushItem:
    kind: str  # text | drawing | image | field | annot
    bbox: tuple[float, float, float, float]  # display space
    xref: int = 0


@dataclass(frozen=True)
class PushRequest:
    dy: float  # display space, positive = down
    items: tuple[PushItem, ...]


@dataclass
class PushPlan:
    delta: fitz.Point  # unrotated page space
    lines: list[dict] = field(default_factory=list)  # text lines to rewrite
    paths: list[dict] = field(default_factory=list)  # drawings to redraw shifted
    keep_paths: list[dict] = field(default_factory=list)  # removed as collateral: redraw in place
    images: list[dict] = field(default_factory=list)
    widgets: list[int] = field(default_factory=list)
    annots: list[int] = field(default_factory=list)
    copies: list[fitz.Rect] = field(default_factory=list)  # copied from the snapshot
    skipped: list[str] = field(default_factory=list)
    snapshot: fitz.Document | None = None

    @property
    def moved(self) -> int:
        return len(self.lines) + len(self.paths) + len(self.images) + len(self.widgets) + len(self.annots)


# ------------------------------------------------------------------ model
def cluster_rects(rects: list[fitz.Rect], tolerance: float = 2.0) -> list[fitz.Rect]:
    """Merge rectangles that touch (within ``tolerance``) into clusters.

    Unlike ``Page.cluster_drawings`` this keeps zero-height rules and lines.
    """
    clusters: list[fitz.Rect] = []
    for rect in sorted((fitz.Rect(r) for r in rects), key=lambda r: (r.y0, r.x0)):
        grown = rect + (-tolerance, -tolerance, tolerance, tolerance)
        merged = True
        while merged:
            merged = False
            for index, cluster in enumerate(clusters):
                if fitz.Rect(grown).intersects(cluster) or _touches(grown, cluster):
                    rect = fitz.Rect(rect) | cluster
                    grown = rect + (-tolerance, -tolerance, tolerance, tolerance)
                    del clusters[index]
                    merged = True
                    break
        clusters.append(fitz.Rect(rect))
    return clusters


def _touches(a: fitz.Rect, b: fitz.Rect) -> bool:
    """Intersection test that also works for degenerate (zero-area) rectangles."""
    return a.x0 <= b.x1 and b.x0 <= a.x1 and a.y0 <= b.y1 and b.y0 <= a.y1


def path_rect(path: dict) -> fitz.Rect:
    half = (path.get("width") or 0) / 2
    return fitz.Rect(path["rect"]) + (-half, -half, half, half)


def drawing_clusters(page: fitz.Page) -> list[fitz.Rect]:
    """Groups of vector graphics (unrotated page space), e.g. a rule, a box, a table grid."""
    paths = page.get_drawings()
    if len(paths) > MAX_PATHS:
        return []
    page_rect = page.rect
    rects = [path_rect(p) for p in paths]
    # Page-sized backgrounds are not "content below" anything.
    rects = [r for r in rects if not (r.width > page_rect.width * 0.9 and r.height > page_rect.height * 0.5)]
    return cluster_rects(rects)


# ------------------------------------------------------------------ planning
def _to_page(page: fitz.Page, bbox: tuple) -> fitz.Rect:
    rect = fitz.Rect(bbox) * page.derotation_matrix
    rect.normalize()
    return rect


def inside(rect: fitz.Rect, area: fitz.Rect) -> bool:
    grown = area + (-PAD, -PAD, PAD, PAD)
    return grown.x0 <= rect.x0 and grown.y0 <= rect.y0 and rect.x1 <= grown.x1 and rect.y1 <= grown.y1


def _centre_in(rect: fitz.Rect, area: fitz.Rect) -> bool:
    centre = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    return _touches(fitz.Rect(centre, centre), area + (-PAD, -PAD, PAD, PAD))


def plan(doc: fitz.Document, page: fitz.Page, request: PushRequest, text_lines: list[dict],
         exclude_lines: list[dict]) -> PushPlan:
    """Work out what moves. ``text_lines`` are the page's lines (from ``extract``)."""
    a = page.derotation_matrix
    origin = fitz.Point(0, 0) * a
    delta = fitz.Point(0, request.dy) * a - origin
    result = PushPlan(fitz.Point(delta.x, delta.y))
    by_kind: dict[str, list[PushItem]] = {}
    for item in request.items:
        by_kind.setdefault(item.kind, []).append(item)

    excluded = [fitz.Rect(line["bbox"]) for line in exclude_lines]
    text_areas = [_to_page(page, item.bbox) for item in by_kind.get("text", [])]
    for line in text_lines:
        rect = fitz.Rect(line["bbox"])
        if any(max(abs(a - b) for a, b in zip(rect, other)) < 0.01 for other in excluded):
            continue
        if any(_centre_in(rect, area) for area in text_areas) and any(s["text"].strip() for s in line["spans"]):
            result.lines.append(line)

    _plan_paths(page, [_to_page(page, i.bbox) for i in by_kind.get("drawing", [])], result)
    _plan_images(page, by_kind.get("image", []), result)
    widget_xrefs = {w.xref for w in page.widgets() or []}
    for item in by_kind.get("field", []):
        if item.xref in widget_xrefs:
            result.widgets.append(item.xref)
        else:
            result.skipped.append("form field")
    for item in by_kind.get("annot", []):
        annot = next((a for a in page.annots() or [] if a.xref == item.xref), None)
        if annot is not None and annot.type[0] in _MOVABLE_ANNOTS:
            result.annots.append(item.xref)
        else:
            result.skipped.append("annotation")
    if result.lines or result.paths or result.images:
        result.snapshot = fitz.open()
        result.snapshot.insert_pdf(doc, from_page=page.number, to_page=page.number)
    return result


def removal_rect(path: dict) -> fitz.Rect:
    return path_rect(path) + (-0.6, -0.6, 0.6, 0.6)


def _plan_paths(page: fitz.Page, areas: list[fitz.Rect], result: PushPlan) -> None:
    if not areas:
        return
    paths = page.get_drawings()
    moving = [p for p in paths if any(inside(path_rect(p), area) for area in areas)]
    removal = [removal_rect(p) for p in moving]
    ids = {id(p) for p in moving}
    # Redaction removes every path fully covered by a removal rectangle: put those back.
    result.keep_paths = [p for p in paths if id(p) not in ids
                         and any(inside(path_rect(p), r + (PAD, PAD, -PAD, -PAD)) for r in removal)]
    result.paths = moving


def _axis_aligned(transform: tuple) -> bool:
    a, b, c, d, _e, _f = transform
    return abs(b) < 1e-3 and abs(c) < 1e-3 and a > 0 and d > 0


def _plan_images(page: fitz.Page, items: list[PushItem], result: PushPlan) -> None:
    if not items:
        return
    infos = page.get_image_info(xrefs=True)
    for item in items:
        area = _to_page(page, item.bbox)
        info = next((i for i in infos if i.get("xref") == item.xref and inside(fitz.Rect(i["bbox"]), area)), None)
        if info is None or item.xref <= 0 or not _axis_aligned(info["transform"]):
            result.skipped.append("image")
            continue
        hit = fitz.Rect(info["bbox"]) + (1, 1, -1, -1)
        if any(o is not info and fitz.Rect(o["bbox"]).intersects(hit) for o in infos):
            result.skipped.append("overlapping image")  # removal would take the other image too
            continue
        result.images.append(info)


# ------------------------------------------------------------------ applying
def text_removal_rects(push_plan: PushPlan) -> list[fitz.Rect]:
    return [fitz.Rect(line["bbox"]) for line in push_plan.lines]


def remove_graphics(page: fitz.Page, push_plan: PushPlan, redact) -> None:
    """Remove moving paths and images (text is removed with the edited box's own lines)."""
    rects = [removal_rect(p) for p in push_plan.paths]
    rects += [fitz.Rect(i["bbox"]) + (1, 1, -1, -1) for i in push_plan.images]
    if rects:
        redact(page, rects, images=fitz.PDF_REDACT_IMAGE_REMOVE,
               graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED, text=fitz.PDF_REDACT_TEXT_NONE)


def place_graphics(page: fitz.Page, push_plan: PushPlan) -> None:
    """Redraw paths, re-place images and move fields/annotations (before text is written)."""
    shift = fitz.Matrix(1, 0, 0, 1, push_plan.delta.x, push_plan.delta.y)
    if push_plan.paths or push_plan.keep_paths:
        shape = page.new_shape()
        for path in push_plan.keep_paths:
            draw_path(shape, path, fitz.Identity)
        for path in push_plan.paths:
            draw_path(shape, path, shift)
        shape.commit(overlay=True)
    for info in push_plan.images:
        page.insert_image(fitz.Rect(info["bbox"]) * shift, xref=info["xref"], keep_proportion=False, overlay=True)
    for widget in page.widgets() or []:
        if widget.xref in push_plan.widgets:
            widget.rect = widget.rect * shift
            widget.update()
    for annot in page.annots() or []:
        if annot.xref in push_plan.annots:
            annot.set_rect(annot.rect * shift)
            annot.update()


def place_copies(page: fitz.Page, push_plan: PushPlan) -> None:
    """Lines whose fonts cannot be rewritten exactly: copy them from the snapshot."""
    if not push_plan.copies or push_plan.snapshot is None:
        return
    shift = fitz.Matrix(1, 0, 0, 1, push_plan.delta.x, push_plan.delta.y)
    for rect in push_plan.copies:
        clip = rect + (-0.5, -0.5, 0.5, 0.5)
        page.show_pdf_page(clip * shift, push_plan.snapshot, 0, clip=clip)


def draw_path(shape: fitz.Shape, path: dict, matrix: fitz.Matrix) -> None:
    for item in path["items"]:
        kind = item[0]
        if kind == "l":
            shape.draw_line(item[1] * matrix, item[2] * matrix)
        elif kind == "re":
            shape.draw_rect(item[1] * matrix)
        elif kind == "qu":
            shape.draw_quad(item[1] * matrix)
        elif kind == "c":
            shape.draw_bezier(item[1] * matrix, item[2] * matrix, item[3] * matrix, item[4] * matrix)
    caps = path.get("lineCap") or (0,)
    shape.finish(
        fill=path.get("fill"),
        color=path.get("color"),
        dashes=path.get("dashes") or None,
        even_odd=bool(path.get("even_odd", False)),
        closePath=bool(path.get("closePath", False)),
        lineJoin=int(path.get("lineJoin") or 0),
        lineCap=int(max(caps)),
        width=path.get("width") or 0,
        stroke_opacity=_opacity(path.get("stroke_opacity")),
        fill_opacity=_opacity(path.get("fill_opacity")),
    )


def _opacity(value: float | None) -> float:
    return 1.0 if value is None else max(0.0, min(1.0, float(value)))
