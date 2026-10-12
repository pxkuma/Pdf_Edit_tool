"""Recover the *exact* text state behind every piece of text on a page.

MuPDF's extraction normalises styles (converts CMYK/spot colours to RGB, folds
horizontal scaling into the size, drops word spacing, rise, render mode and the
ExtGState). To rewrite text so it is indistinguishable from the original we run
a small content-stream interpreter that records, for each text-showing operator,
the full graphics/text state that was in effect.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field, replace

import pymupdf as fitz

from . import fontres, pdfobj
from .contentparse import Name, Tokenizer

log = logging.getLogger(__name__)

MAX_CONTENT_BYTES = 8 * 1024 * 1024
MAX_FORM_DEPTH = 6
COLOR_OPS = {"g", "rg", "k", "sc", "scn", "G", "RG", "K", "SC", "SCN"}
RENDER_MODES = {0: "fill", 1: "stroke", 2: "fill + stroke", 3: "invisible", 4: "fill (clip)",
                5: "stroke (clip)", 6: "fill + stroke (clip)", 7: "clip"}


@dataclass(frozen=True)
class ResourceRef:
    """A named resource and the object whose /Resources defines it (0 = page)."""

    owner: int
    name: str


@dataclass(frozen=True)
class Paint:
    """A colour as raw PDF operators, e.g. ``0 0 0 1 k`` or ``/CS0 cs 0.4 scn``."""

    space: ResourceRef | None  # named colour space (None for device spaces)
    ops: str  # may contain "{space}" / "{pattern}" placeholders for resource names
    kind: str  # "gray" | "rgb" | "cmyk" | "named"
    pattern: ResourceRef | None = None


@dataclass(frozen=True)
class TextRecord:
    origin: tuple[float, float]  # MuPDF (unrotated, y-down) coordinates of the first glyph
    direction: tuple[float, float]  # unit baseline direction in MuPDF coordinates
    font: ResourceRef
    font_xref: int
    font_size: float  # Tf operand
    char_spacing: float  # Tc
    word_spacing: float  # Tw
    hscale: float  # Tz / 100
    rise: float  # Ts
    render_mode: int  # Tr
    line_width: float  # in page units
    fill: Paint
    stroke: Paint
    gstates: tuple[ResourceRef, ...]
    axis_x: float  # length of the text-space x axis in page units (Tm x CTM)
    axis_y: float  # length of the text-space y axis in page units
    skew: float  # shear of the y axis along the baseline

    # ----- values normalised to page units (what the writer consumes) -----
    @property
    def effective_size(self) -> float:
        return self.font_size * self.axis_y

    @property
    def effective_hscale(self) -> float:
        return self.hscale * self.axis_x / self.axis_y * 100.0 if self.axis_y else 100.0

    @property
    def page_char_spacing(self) -> float:
        return self.char_spacing * self.axis_y

    @property
    def page_word_spacing(self) -> float:
        return self.word_spacing * self.axis_y

    @property
    def page_rise(self) -> float:
        return self.rise * self.axis_y


@dataclass
class _State:
    ctm: fitz.Matrix = field(default_factory=lambda: fitz.Matrix(1, 0, 0, 1, 0, 0))
    fill: Paint = Paint(None, "0 g", "gray")
    stroke: Paint = Paint(None, "0 G", "gray")
    fill_space: ResourceRef | None = None
    stroke_space: ResourceRef | None = None
    line_width: float = 1.0
    gstates: tuple[ResourceRef, ...] = ()
    font: ResourceRef | None = None
    font_size: float = 0.0
    char_spacing: float = 0.0
    word_spacing: float = 0.0
    hscale: float = 1.0
    leading: float = 0.0
    rise: float = 0.0
    render_mode: int = 0

    def copy(self) -> "_State":
        return replace(self)


def _num(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _fmt(value: float) -> str:
    text = f"{value:.5f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _matrix(values: list) -> fitz.Matrix:
    nums = [_num(v) for v in values[:6]] + [0.0] * (6 - len(values[:6]))
    return fitz.Matrix(*nums)


class _Interpreter:
    def __init__(self, doc: fitz.Document, page: fitz.Page) -> None:
        self.doc = doc
        self.page = page
        self.to_mupdf = page.transformation_matrix
        self.records: list[TextRecord] = []
        self.font_xrefs: dict[tuple[int, str], int] = {}
        self.fonts: dict[int, fontres.EmbeddedFont | None] = {}
        for xref, _ext, _type, _base, name, _enc, *rest in page.get_fonts(full=True):
            referencer = rest[0] if rest else 0
            owner = 0 if referencer in (0, page.xref) else referencer
            self.font_xrefs.setdefault((owner, name), xref)

    # -------------------------------------------------------------- helpers
    def _font(self, xref: int) -> fontres.EmbeddedFont | None:
        if xref not in self.fonts:
            try:
                self.fonts[xref] = fontres.analyze_font(self.doc, xref, verify=False)
            except Exception:  # noqa: BLE001 - broken fonts must not break parsing
                self.fonts[xref] = None
        return self.fonts[xref]

    def _font_xref(self, ref: ResourceRef) -> int:
        xref = self.font_xrefs.get((ref.owner, ref.name))
        if xref is None and ref.owner:
            xref = self.font_xrefs.get((0, ref.name))
        if xref is None:
            value = resource_value(self.doc, self.page, ResourceRef(ref.owner, ref.name), "Font")
            xref = pdfobj.ref_xref(value) if value else None
        return xref or 0

    def _advance(self, state: _State, font: fontres.EmbeddedFont | None, payload: bytes) -> float:
        """Horizontal displacement (text space) of a string."""
        step = font.code_bytes if font else 1
        total = 0.0
        for i in range(0, len(payload) - step + 1, step):
            code = payload[i:i + step]
            width = font.width_of(code) / 1000.0 if font else 0.5
            spacing = state.char_spacing + (state.word_spacing if step == 1 and code == b" " else 0.0)
            total += (width * state.font_size + spacing) * state.hscale
        return total

    # -------------------------------------------------------------- recording
    def _record(self, state: _State, tm: fitz.Matrix) -> None:
        if state.font is None:
            return
        trm = tm * state.ctm
        origin_pdf = fitz.Point(0, state.rise) * trm
        origin = origin_pdf * self.to_mupdf
        ax, ay = (trm.a, trm.b), (trm.c, trm.d)
        lx, ly = math.hypot(*ax), math.hypot(*ay)
        if lx < 1e-9 or ly < 1e-9:
            return
        tip = fitz.Point(origin_pdf.x + ax[0] / lx, origin_pdf.y + ax[1] / lx) * self.to_mupdf
        direction = (tip.x - origin.x, tip.y - origin.y)
        norm = math.hypot(*direction) or 1.0
        ux = (ax[0] / lx, ax[1] / lx)
        # Height = component of the y axis perpendicular to the baseline; the
        # parallel component is a shear (e.g. synthetic oblique text).
        ly = abs(ux[0] * ay[1] - ux[1] * ay[0]) or ly
        skew = (ay[0] * ux[0] + ay[1] * ux[1]) / ly
        ctm_scale = math.sqrt(abs(state.ctm.a * state.ctm.d - state.ctm.b * state.ctm.c)) or 1.0
        self.records.append(TextRecord(
            origin=(origin.x, origin.y),
            direction=(direction[0] / norm, direction[1] / norm),
            font=state.font,
            font_xref=self._font_xref(state.font),
            font_size=state.font_size,
            char_spacing=state.char_spacing,
            word_spacing=state.word_spacing,
            hscale=state.hscale,
            rise=state.rise,
            render_mode=state.render_mode,
            line_width=state.line_width * ctm_scale,
            fill=state.fill,
            stroke=state.stroke,
            gstates=state.gstates,
            axis_x=lx,
            axis_y=ly,
            skew=skew,
        ))

    def _show(self, state: _State, tm: fitz.Matrix, payload: object) -> fitz.Matrix:
        """Record a text-showing operator; return the text matrix after it."""
        self._record(state, tm)
        font = self._font(self._font_xref(state.font)) if state.font else None
        parts = payload if isinstance(payload, list) else [payload]
        tx = 0.0
        for part in parts:
            if isinstance(part, bytes):
                tx += self._advance(state, font, part)
            elif isinstance(part, (int, float)) and not isinstance(part, bool):
                tx -= part / 1000.0 * state.font_size * state.hscale
        return fitz.Matrix(1, 0, 0, 1, tx, 0) * tm

    # -------------------------------------------------------------- colour
    def _paint(self, op: str, operands: list, state: _State) -> None:
        stroke = op.isupper()
        nums = " ".join(_fmt(_num(v)) for v in operands if isinstance(v, (int, float)) and not isinstance(v, bool))
        names = [v for v in operands if isinstance(v, Name)]
        if op.lower() == "g":
            paint = Paint(None, f"{nums} {op}", "gray")
        elif op.lower() == "rg":
            paint = Paint(None, f"{nums} {op}", "rgb")
        elif op.lower() == "k":
            paint = Paint(None, f"{nums} {op}", "cmyk")
        else:
            space = state.stroke_space if stroke else state.fill_space
            pattern = ResourceRef(space.owner if space else 0, str(names[0])) if names else None
            body = f"{nums}{' /{pattern}' if pattern else ''} {op}".strip()
            set_space = "CS" if stroke else "cs"
            if space is None:
                paint = Paint(None, body, "named", pattern)
            elif space.name in ("DeviceGray", "DeviceRGB", "DeviceCMYK"):
                kind = {"DeviceGray": "gray", "DeviceRGB": "rgb", "DeviceCMYK": "cmyk"}[space.name]
                paint = Paint(None, f"/{space.name} {set_space} {body}", kind, pattern)
            else:
                paint = Paint(space, f"/{{space}} {set_space} {body}", "named", pattern)
        if stroke:
            state.stroke = paint
        else:
            state.fill = paint

    # -------------------------------------------------------------- main loop
    def run(self, data: bytes, owner: int, base: _State, depth: int = 0) -> None:
        state = base.copy()
        stack: list[_State] = []
        tm = tlm = fitz.Matrix(1, 0, 0, 1, 0, 0)
        for operands, op in Tokenizer(data):
            if op == "q":
                stack.append(state.copy())
            elif op == "Q":
                if stack:
                    state = stack.pop()
            elif op == "cm" and len(operands) >= 6:
                state.ctm = _matrix(operands) * state.ctm
            elif op == "w" and operands:
                state.line_width = _num(operands[0], 1.0)
            elif op == "gs" and operands and isinstance(operands[0], Name):
                state.gstates = state.gstates + (ResourceRef(owner, str(operands[0])),)
            elif op in ("cs", "CS") and operands and isinstance(operands[0], Name):
                ref = ResourceRef(owner, str(operands[0]))
                if op == "cs":
                    state.fill_space = ref
                else:
                    state.stroke_space = ref
            elif op in COLOR_OPS:
                self._paint(op, operands, state)
            elif op == "BT":
                tm = tlm = fitz.Matrix(1, 0, 0, 1, 0, 0)
            elif op == "Tf" and len(operands) >= 2:
                state.font = ResourceRef(owner, str(operands[0]))
                state.font_size = _num(operands[1], 0.0)
            elif op == "Tc" and operands:
                state.char_spacing = _num(operands[0])
            elif op == "Tw" and operands:
                state.word_spacing = _num(operands[0])
            elif op == "Tz" and operands:
                state.hscale = _num(operands[0], 100.0) / 100.0
            elif op == "TL" and operands:
                state.leading = _num(operands[0])
            elif op == "Ts" and operands:
                state.rise = _num(operands[0])
            elif op == "Tr" and operands:
                state.render_mode = int(_num(operands[0]))
            elif op in ("Td", "TD") and len(operands) >= 2:
                tx, ty = _num(operands[0]), _num(operands[1])
                if op == "TD":
                    state.leading = -ty
                tlm = fitz.Matrix(1, 0, 0, 1, tx, ty) * tlm
                tm = tlm
            elif op == "Tm" and len(operands) >= 6:
                tm = tlm = _matrix(operands)
            elif op == "T*":
                tlm = fitz.Matrix(1, 0, 0, 1, 0, -state.leading) * tlm
                tm = tlm
            elif op in ("Tj", "TJ") and operands:
                tm = self._show(state, tm, operands[-1])
            elif op in ("'", '"') and operands:
                if op == '"' and len(operands) >= 3:
                    state.word_spacing, state.char_spacing = _num(operands[0]), _num(operands[1])
                tlm = fitz.Matrix(1, 0, 0, 1, 0, -state.leading) * tlm
                tm = self._show(state, tlm, operands[-1])
            elif op == "Do" and operands and isinstance(operands[0], Name) and depth < MAX_FORM_DEPTH:
                self._form(str(operands[0]), owner, state, depth)

    def _form(self, name: str, owner: int, state: _State, depth: int) -> None:
        value = resource_value(self.doc, self.page, ResourceRef(owner, name), "XObject")
        xref = pdfobj.ref_xref(value) if value else None
        if not xref or pdfobj.read_name(self.doc, xref, "Subtype") != "Form":
            return
        try:
            data = self.doc.xref_stream(xref) or b""
        except Exception:  # noqa: BLE001
            return
        matrix = pdfobj.read_number_array(self.doc, xref, "Matrix")
        inner = state.copy()
        if len(matrix) == 6:
            inner.ctm = fitz.Matrix(*matrix) * state.ctm
        has_resources = pdfobj.get_key(self.doc, xref, "Resources")[0] != "null"
        self.run(data, xref if has_resources else owner, inner, depth + 1)


def resource_value(doc: fitz.Document, page: fitz.Page, ref: ResourceRef, category: str) -> str | None:
    """Raw value (``"12 0 R"`` or an inline object) of a named resource."""
    if ref.owner:
        kind, value = pdfobj.get_key(doc, ref.owner, f"Resources/{category}/{ref.name}")
        if kind != "null":
            return value
    return pdfobj.resource_exists(doc, page, category, ref.name)


def page_text_records(doc: fitz.Document, page: fitz.Page) -> list[TextRecord]:
    try:
        data = page.read_contents() or b""
    except Exception:  # noqa: BLE001
        return []
    if len(data) > MAX_CONTENT_BYTES:
        log.info("Page %s content too large for exact style analysis", page.number)
        return []
    interpreter = _Interpreter(doc, page)
    try:
        interpreter.run(data, 0, _State())
    except Exception:  # noqa: BLE001 - malformed content: fall back to estimates
        log.debug("content interpretation failed on page %s", page.number, exc_info=True)
    return interpreter.records


def match_record(records: list[TextRecord], origin: tuple[float, float], direction: tuple[float, float],
                 font_name: str = "", doc: fitz.Document | None = None) -> TextRecord | None:
    """The text operator that produced a span starting at ``origin``.

    Picks the closest operator starting at or before the span on the same baseline,
    preferring operators that use the span's font.
    """
    wanted = fontres.normalize_font_name(font_name)
    best: tuple[tuple[int, float], TextRecord] | None = None
    for record in records:
        dx, dy = origin[0] - record.origin[0], origin[1] - record.origin[1]
        cross = abs(record.direction[0] * direction[1] - record.direction[1] * direction[0])
        if cross > 0.05:
            continue
        along = dx * direction[0] + dy * direction[1]
        perpendicular = abs(-dx * direction[1] + dy * direction[0])
        if perpendicular > max(0.75, record.effective_size * 0.08) or along < -0.75:
            continue
        same_font = 0
        if wanted and doc is not None and record.font_xref:
            base = pdfobj.read_name(doc, record.font_xref, "BaseFont")
            same_font = 0 if fontres.normalize_font_name(base) == wanted else 1
        key = (same_font, along)
        if best is None or key < best[0]:
            best = (key, record)
    return best[1] if best else None


def describe_paint(doc: fitz.Document, page: fitz.Page, paint: Paint) -> str:
    if paint.kind == "gray":
        return "Gray"
    if paint.kind == "rgb":
        return "RGB"
    if paint.kind == "cmyk":
        return "CMYK"
    if paint.space is None:
        return "Color"
    value = resource_value(doc, page, paint.space, "ColorSpace") or ""
    target = pdfobj.ref_xref(value)
    text = doc.xref_object(target, compressed=True) if target else value
    for family in ("Separation", "DeviceN", "ICCBased", "Indexed", "Pattern", "Lab", "CalRGB", "CalGray"):
        if f"/{family}" in text:
            if family == "Separation":
                parts = text.split("/Separation", 1)[1].split()
                return f"Spot color {parts[0].lstrip('/').replace('#20', ' ')}" if parts else "Spot color"
            return family
    return "Color"


def page_resource_name(doc: fitz.Document, page: fitz.Page, ref: ResourceRef, category: str) -> str | None:
    """Make a resource usable from the page's own content; return its page-level name."""
    if not ref.owner:
        return ref.name if pdfobj.resource_exists(doc, page, category, ref.name) is not None else None
    value = resource_value(doc, page, ref, category)
    if value is None:
        return None
    name = "PSR" + "".join(ch for ch in f"{ref.owner}{ref.name}" if ch.isalnum())[:40]
    if pdfobj.resource_exists(doc, page, category, name) is None:
        pdfobj.add_resource(doc, page, category, name, value)
    return name


def resolve_paint(doc: fitz.Document, page: fitz.Page, paint: Paint) -> str | None:
    """Raw colour operators valid in page content, or None if they can't be reproduced."""
    ops = paint.ops
    if paint.space is not None:
        name = page_resource_name(doc, page, paint.space, "ColorSpace")
        if name is None:
            return None
        ops = ops.replace("{space}", name)
    if paint.pattern is not None:
        name = page_resource_name(doc, page, paint.pattern, "Pattern")
        if name is None:
            return None
        ops = ops.replace("{pattern}", name)
    return ops


def resolve_gstates(doc: fitz.Document, page: fitz.Page, refs: tuple[ResourceRef, ...]) -> tuple[str, ...]:
    names = []
    for ref in refs:
        name = page_resource_name(doc, page, ref, "ExtGState")
        if name:
            names.append(name)
    return tuple(names)


def fill_opacity(doc: fitz.Document, page: fitz.Page, record: TextRecord) -> float:
    """Fill alpha (/ca) in effect for a record (1.0 when not set)."""
    alpha = 1.0
    for ref in record.gstates:
        value = resource_value(doc, page, ref, "ExtGState") or ""
        target = pdfobj.ref_xref(value)
        text = doc.xref_object(target, compressed=True) if target else value
        match = re.search(r"/ca\s+([0-9.]+)", text)
        if match:
            alpha = float(match.group(1))
    return max(0.0, min(1.0, alpha))
