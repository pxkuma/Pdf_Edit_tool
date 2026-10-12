"""High level text editing: replace spans, reflow paragraphs, add new text."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace

import pymupdf as fitz

from . import extract, fontres, pdfobj, textstate
from .fonts import FontCatalog, FontFace, style_from_name
from .geometry import from_display_point, from_display_vector, hex_to_rgb, shrink_for_redaction
from .textwriter import FontChain, Glyph, PlacedLine, TextStyle, line_width, write_lines


class TextEditError(ValueError):
    """Raised for edit requests that cannot be applied (reported to the user)."""


@dataclass(frozen=True)
class StyleRequest:
    font: str = "original"  # "original" | "doc:<xref>" | "face:<id>"
    size: float | None = None
    color: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool = False
    strike: bool = False
    opacity: float | None = None
    char_spacing: float | None = None
    hscale: float | None = None


@dataclass(frozen=True)
class SpanEdit:
    bbox: tuple[float, float, float, float]
    origin: tuple[float, float] | None
    original_text: str
    text: str
    style: StyleRequest = field(default_factory=StyleRequest)
    dx: float = 0.0
    dy: float = 0.0
    fit_width: bool = False
    reflow: bool = True


@dataclass(frozen=True)
class BlockEdit:
    bbox: tuple[float, float, float, float]
    text: str
    style: StyleRequest = field(default_factory=StyleRequest)
    align: str = "left"
    line_height: float | None = None


@dataclass(frozen=True)
class NewText:
    x: float
    y: float
    text: str
    style: StyleRequest = field(default_factory=StyleRequest)
    width: float | None = None
    align: str = "left"
    line_height: float = 1.2
    rotation: int = 0


@dataclass(frozen=True)
class EditReport:
    fonts_used: list[str]
    missing_chars: list[str]
    exact_font: bool


# --------------------------------------------------------------- font logic
def _page_font_candidates(doc: fitz.Document, page: fitz.Page, span_font: str) -> list[fontres.EmbeddedFont]:
    wanted = fontres.normalize_font_name(span_font)
    results = []
    seen: set[int] = set()
    for xref, _ext, _type, basefont, _name, _enc, *_ in page.get_fonts(full=True):
        if xref <= 0 or xref in seen:
            continue
        name = fontres.normalize_font_name(basefont)
        if name == wanted or (wanted and (name.startswith(wanted) or wanted.startswith(name))):
            seen.add(xref)
            analysed = fontres.analyze_font(doc, xref)
            if analysed is not None:
                results.append(analysed)
    return results


def resolve_span_font(doc: fitz.Document, page: fitz.Page, span: dict) -> fontres.EmbeddedFont | None:
    candidates = _page_font_candidates(doc, page, span["font"])
    if not candidates:
        return None
    best = max(candidates, key=lambda font: font.coverage(span["text"]))
    return best if best.coverage(span["text"]) >= 0.6 else None


def _record_font(doc: fitz.Document, span: dict) -> fontres.EmbeddedFont | None:
    """The exact font object that drew the span (from the content stream)."""
    record = span.get("record")
    if record is None or not record.font_xref:
        return None
    font = fontres.analyze_font(doc, record.font_xref)
    if font is None or font.coverage(span.get("primary_text", span["text"])) < 0.6:
        return None
    return font


def _catalog_face(catalog: FontCatalog, face_id: str, bold: bool, italic: bool) -> FontFace:
    face = catalog.get(face_id)
    if face is None:
        raise TextEditError("The selected font is not available.")
    return catalog.pick_variant(face.family, bold, italic) or face


def _span_flags(span: dict) -> dict:
    flags = extract.span_style_flags(span)
    name_bold, name_italic = style_from_name(span["font"])
    return {**flags, "bold": flags["bold"] or name_bold, "italic": flags["italic"] or name_italic}


@dataclass
class _FontPlan:
    chain: FontChain
    bold_synth: bool
    italic_synth: bool


def plan_fonts(
    doc: fitz.Document,
    page: fitz.Page,
    catalog: FontCatalog,
    request: StyleRequest,
    span: dict | None,
) -> _FontPlan:
    base = _span_flags(span) if span else {"bold": False, "italic": False, "serif": False, "mono": False}
    bold = base["bold"] if request.bold is None else request.bold
    italic = base["italic"] if request.italic is None else request.italic
    font_name = span["font"] if span else "Helvetica"

    if request.font.startswith("face:"):
        face = _catalog_face(catalog, request.font[5:], bold, italic)
        return _FontPlan(FontChain.build(catalog, None, face), False, False)

    embedded: fontres.EmbeddedFont | None = None
    if request.font.startswith("doc:"):
        try:
            embedded = fontres.analyze_font(doc, int(request.font[4:]))
        except ValueError as exc:
            raise TextEditError("Invalid document font reference.") from exc
        if embedded is not None:
            font_name = embedded.base_name
            base = {**base, **dict(zip(("bold", "italic"), style_from_name(font_name)))}
    elif span is not None:
        embedded = _record_font(doc, span) or resolve_span_font(doc, page, span)

    substitute = catalog.substitute(font_name, bold, italic, base["serif"], base["mono"])
    chain = FontChain.build(catalog, embedded, substitute)
    if embedded is None:
        return _FontPlan(chain, False, False)
    return _FontPlan(chain, bold and not base["bold"], italic and not base["italic"])


def _style(
    request: StyleRequest,
    span: dict | None,
    plan: _FontPlan,
    doc: fitz.Document | None = None,
    page: fitz.Page | None = None,
    default_size: float = 12.0,
) -> TextStyle:
    record = span.get("record") if span else None
    if record is not None and doc is not None and page is not None:
        return _exact_style(request, span, plan, record, doc, page)
    color_default = hex_to_rgb(extract.color_to_hex(span.get("color"))) if span else (0.0, 0.0, 0.0)
    opacity_default = span.get("alpha", 255) / 255.0 if span else 1.0
    size = request.size if request.size else (span["size"] if span else default_size)
    _check_size(size)
    return TextStyle(
        size=size,
        color=hex_to_rgb(request.color, color_default),
        opacity=max(0.0, min(1.0, request.opacity if request.opacity is not None else opacity_default)),
        bold_synth=plan.bold_synth,
        italic_synth=plan.italic_synth,
        underline=request.underline,
        strike=request.strike,
        char_spacing=request.char_spacing or 0.0,
        hscale=max(10.0, min(400.0, request.hscale or 100.0)),
    )


def _check_size(size: float) -> None:
    if size <= 0 or size > 1000:
        raise TextEditError("Font size must be between 0 and 1000 pt.")


def _exact_style(request: StyleRequest, span: dict, plan: _FontPlan, record: textstate.TextRecord,
                 doc: fitz.Document, page: fitz.Page) -> TextStyle:
    """Reproduce the original text state exactly, applying only what the user changed."""
    size = request.size or record.effective_size
    _check_size(size)
    scale = size / record.effective_size if record.effective_size else 1.0
    color = hex_to_rgb(request.color, hex_to_rgb(extract.color_to_hex(span.get("color"))))
    return TextStyle(
        size=size,
        color=color,
        opacity=1.0 if request.opacity is None else max(0.0, min(1.0, request.opacity)),
        bold_synth=plan.bold_synth,
        italic_synth=plan.italic_synth,
        underline=request.underline,
        strike=request.strike,
        char_spacing=record.page_char_spacing * scale if request.char_spacing is None else request.char_spacing,
        hscale=max(10.0, min(400.0, request.hscale or record.effective_hscale)),
        word_spacing=record.page_word_spacing * scale,
        rise=record.page_rise * scale,
        skew=record.skew,
        render_mode=record.render_mode,
        line_width=record.line_width * scale,
        **bind_resources(request, record, doc, page),
    )


def bind_resources(request: StyleRequest, record: textstate.TextRecord, doc: fitz.Document, page: fitz.Page) -> dict:
    """Colour operators and graphics states of the original, valid on this page.

    Must run *after* redaction: MuPDF rebuilds the page resource dictionary when
    applying redactions and drops entries that are not used yet.
    """
    fill_ops = stroke_ops = None
    if request.color is None:
        fill_ops = textstate.resolve_paint(doc, page, record.fill)
        stroke_ops = textstate.resolve_paint(doc, page, record.stroke)
    elif record.render_mode in (2, 6):
        stroke_ops = textstate.resolve_paint(doc, page, record.stroke)
    return {"fill_ops": fill_ops, "stroke_ops": stroke_ops,
            "gstates": textstate.resolve_gstates(doc, page, record.gstates)}


def _rebind(job: "_WriteJob", doc: fitz.Document, page: fitz.Page) -> None:
    if job.record is not None:
        job.style = replace(job.style, **bind_resources(job.request, job.record, doc, page))


def _report(chain: FontChain) -> EditReport:
    names = []
    exact = True
    for key in sorted(chain.used_keys):
        if key.startswith("e") and chain.embedded is not None:
            names.append(chain.embedded.display_name)
        else:
            face = chain.face_for_key(key)
            if face:
                names.append(f"{face.family} {face.style}")
                exact = False if chain.embedded is not None else exact
    return EditReport(names, sorted(chain.missing), exact and not chain.missing)


# --------------------------------------------------------------- redaction
def redact_areas(page: fitz.Page, rects: list[fitz.Rect], fill: tuple | bool = False,
                 images: int = fitz.PDF_REDACT_IMAGE_NONE,
                 graphics: int = fitz.PDF_REDACT_LINE_ART_NONE) -> None:
    """Apply redactions for ``rects`` without applying pre-existing redact annots."""
    pending = []
    for annot in list(page.annots(types=[fitz.PDF_ANNOT_REDACT]) or []):
        pending.append((fitz.Rect(annot.rect), annot.info))
        page.delete_annot(annot)
    for rect in rects:
        if not rect.is_empty:
            page.add_redact_annot(rect, fill=fill)
    page.apply_redactions(images=images, graphics=graphics, text=fitz.PDF_REDACT_TEXT_REMOVE)
    for rect, info in pending:
        restored = page.add_redact_annot(rect)
        restored.set_info(info)
        restored.update()


def _auto_char_spacing(span: dict, chain: FontChain, style: TextStyle) -> float:
    """Detect letter spacing used by the original text so edits keep the rhythm."""
    text = span["text"]
    if chain.embedded is None or len(text.strip()) < 3:
        return 0.0
    glyphs = chain.encode(text)
    keys_before = set(chain.used_keys)
    chain.used_keys.clear()
    chain.missing.clear()
    real = [g for g in glyphs if g.font_key]
    if len(glyphs) != len(text) or not real or keys_before - {f"e{chain.embedded.xref}"}:
        return 0.0
    # Distance between the first and the last glyph origin: unaffected by glyph
    # shapes (skew, overhangs), so it isolates the spacing that was applied.
    direction = span["record"].direction if span.get("record") else (1.0, 0.0)
    first, last = span["origin"], span.get("last_origin", span["origin"])
    actual = (last[0] - first[0]) * direction[0] + (last[1] - first[1]) * direction[1]
    natural = line_width(glyphs[:-1], replace(style, char_spacing=0.0))
    counted = sum(1 for g in glyphs[:-1] if g.font_key)
    if actual <= 0 or not counted:
        return 0.0
    spacing = (actual - natural) / counted / (style.hscale / 100.0)
    return round(spacing, 3) if style.size * 0.02 < abs(spacing) < style.size * 0.5 else 0.0


def _advance(span: dict, direction: tuple[float, float]) -> float:
    rect = fitz.Rect(span["bbox"])
    return abs(direction[0]) * rect.width + abs(direction[1]) * rect.height


@dataclass
class _WriteJob:
    origin: tuple[float, float]
    glyphs: list[Glyph]
    style: TextStyle
    chain: FontChain
    record: textstate.TextRecord | None = None
    request: StyleRequest = field(default_factory=StyleRequest)


def _span_job(
    doc: fitz.Document,
    page: fitz.Page,
    catalog: FontCatalog,
    span: dict,
    text: str,
    request: StyleRequest,
    fit_width: bool = False,
) -> _WriteJob:
    plan = plan_fonts(doc, page, catalog, request, span)
    style = _style(request, span, plan, doc, page)
    record = span.get("record")
    if request.char_spacing is None and (record is None or not record.char_spacing):
        # Spacing done with TJ adjustments rather than Tc: measure it instead.
        spacing = _auto_char_spacing(span, plan.chain, style)
        style = replace(style, char_spacing=spacing)
    glyphs = plan.chain.encode(text)
    if fit_width and glyphs:
        natural = line_width(glyphs, style)
        if natural > 0:
            hscale = style.hscale * fitz.Rect(span["bbox"]).width / natural
            style = replace(style, hscale=max(30.0, min(300.0, hscale)))
    origin = (span["origin"][0], span["origin"][1])
    if style.rise:
        # MuPDF reports the raised glyph origin; the writer re-applies the rise (Ts).
        direction = record.direction if record is not None else (1.0, 0.0)
        origin = (origin[0] - direction[1] * style.rise, origin[1] + direction[0] * style.rise)
    return _WriteJob(origin, glyphs, style, plan.chain, record, request)


def _reflow_jobs(
    doc: fitz.Document,
    page: fitz.Page,
    catalog: FontCatalog,
    followers: list[dict],
    delta: float,
    direction: tuple[float, float],
) -> list[tuple[dict, _WriteJob]]:
    """Shift the spans following an edited span along the line by ``delta`` points.

    Returns an empty list when any follower cannot be rewritten with its exact
    original font (we never degrade untouched text just to close a gap).
    """
    jobs = []
    for span in followers:
        job = _span_job(doc, page, catalog, span, span["text"], StyleRequest())
        embedded = job.chain.embedded
        primary = span.get("primary_text", span["text"])
        if embedded is None or job.chain.missing or embedded.coverage(primary) < 1.0:
            return []
        job.origin = (job.origin[0] + direction[0] * delta, job.origin[1] + direction[1] * delta)
        jobs.append((span, job))
    return jobs


def _following_runs(runs: list[dict], index: int, direction: tuple[float, float]) -> list[dict]:
    result = []
    previous = fitz.Rect(runs[index]["bbox"])
    size = runs[index]["size"]
    for candidate in runs[index + 1:]:
        rect = fitz.Rect(candidate["bbox"])
        if extract._advance_gap(previous, rect, direction) > size * 2.5:
            break  # far away: probably another column or a right-aligned value
        result.append(candidate)
        previous = rect
    return result


# --------------------------------------------------------------- operations
def edit_span(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog, edit: SpanEdit) -> EditReport:
    found = extract.find_span(page, edit.bbox, edit.origin, edit.original_text)
    if found is None:
        raise TextEditError("The text you edited could not be found on the page any more. Reload and try again.")
    line, runs, index = found
    span = runs[index]
    direction = tuple(line.get("dir", (1.0, 0.0)))
    main = _span_job(doc, page, catalog, span, edit.text, edit.style, edit.fit_width)
    moved = bool(edit.dx or edit.dy)
    if moved:
        move = _display_delta(page, edit.dx, edit.dy)
        main.origin = (main.origin[0] + move[0], main.origin[1] + move[1])
    followers: list[tuple[dict, _WriteJob]] = []
    if edit.reflow and not moved and not edit.fit_width:
        delta = line_width(main.glyphs, main.style) - _advance(span, direction)
        if abs(delta) > 0.05:
            candidates = _following_runs(runs, index, direction)
            followers = _reflow_jobs(doc, page, catalog, candidates, delta, direction)
    rects = [shrink_for_redaction(fitz.Rect(s["bbox"]), direction) for s in [span] + [f[0] for f in followers]]
    redact_areas(page, rects)
    for job in [main] + [f[1] for f in followers]:
        _rebind(job, doc, page)
        write_lines(doc, page, [PlacedLine(job.origin, direction, job.glyphs)], job.style, job.chain)
    return _report(main.chain)


def _display_delta(page: fitz.Page, dx: float, dy: float) -> tuple[float, float]:
    a = from_display_point(page, (0.0, 0.0))
    b = from_display_point(page, (dx, dy))
    return (b.x - a.x, b.y - a.y)


def _wrap(chain: FontChain, text: str, style: TextStyle, max_width: float | None) -> list[tuple[list[Glyph], bool]]:
    """Return lines as (glyphs, is_paragraph_end)."""
    result: list[tuple[list[Glyph], bool]] = []
    for paragraph in text.replace("\r\n", "\n").split("\n"):
        words = paragraph.split(" ")
        current: list[Glyph] = []
        for word in words:
            word_glyphs = chain.encode(word)
            candidate = current + (chain.encode(" ") if current else []) + word_glyphs
            if max_width and current and line_width(candidate, style) > max_width:
                result.append((current, False))
                current = word_glyphs
            else:
                current = candidate
        result.append((current, True))
    return result


def _align_offset(width: float, available: float | None, align: str) -> float:
    if not available or align in ("left", "justify"):
        return 0.0
    free = max(0.0, available - width)
    return free / 2 if align == "center" else free


def _layout(
    chain: FontChain,
    text: str,
    style: TextStyle,
    first_origin: tuple[float, float],
    direction: tuple[float, float],
    max_width: float | None,
    step: float,
    align: str,
) -> list[PlacedLine]:
    down = (-direction[1], direction[0])
    placed = []
    for index, (glyphs, paragraph_end) in enumerate(_wrap(chain, text, style, max_width)):
        width = line_width(glyphs, style)
        extra = 0.0
        if align == "justify" and max_width and not paragraph_end:
            spaces = sum(1 for g in glyphs if g.char == " ")
            extra = (max_width - width) / spaces if spaces else 0.0
        shift = _align_offset(width, max_width, align)
        origin = (
            first_origin[0] + down[0] * step * index + direction[0] * shift,
            first_origin[1] + down[1] * step * index + direction[1] * shift,
        )
        placed.append(PlacedLine(origin, direction, glyphs, extra))
    return placed


def edit_block(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog, edit: BlockEdit) -> EditReport:
    block = extract.find_block(page, edit.bbox)
    if block is None:
        raise TextEditError("The paragraph could not be found on the page any more.")
    lines = [line for line in block["lines"] if any(s["text"].strip() for s in line["spans"])]
    if not lines:
        raise TextEditError("The paragraph contains no editable text.")
    direction = tuple(lines[0].get("dir", (1.0, 0.0)))
    tagged = extract.tagged_font_names(page)
    records = textstate.page_text_records(doc, page)
    first_runs = extract.attach_records(doc, extract.line_runs(lines[0], tagged), direction, records, tagged)
    first_span = max(first_runs, key=lambda s: len(s["text"]))
    plan = plan_fonts(doc, page, catalog, edit.style, first_span)
    style = _style(edit.style, first_span, plan, doc, page)
    step = _line_step(lines, direction, style.size, edit.line_height)
    origin = _line_start(lines[0], direction)
    if style.rise:
        origin = (origin[0] - direction[1] * style.rise, origin[1] + direction[0] * style.rise)
    block_rect = fitz.Rect(block["bbox"])
    width = block_rect.width if abs(direction[0]) >= abs(direction[1]) else block_rect.height
    placed = _layout(plan.chain, edit.text, style, origin, direction, width + 0.5, step, edit.align)
    redact_areas(page, [shrink_for_redaction(fitz.Rect(line["bbox"]), direction) for line in lines])
    if first_span.get("record") is not None:
        style = replace(style, **bind_resources(edit.style, first_span["record"], doc, page))
    write_lines(doc, page, placed, style, plan.chain)
    return _report(plan.chain)


def _line_start(line: dict, direction: tuple[float, float]) -> tuple[float, float]:
    span = line["spans"][0]
    return (span["origin"][0], span["origin"][1])


def _line_step(lines: list[dict], direction: tuple[float, float], size: float, factor: float | None) -> float:
    if factor:
        return size * factor
    down = (-direction[1], direction[0])
    origins = [line["spans"][0]["origin"] for line in lines]
    deltas = [
        (b[0] - a[0]) * down[0] + (b[1] - a[1]) * down[1]
        for a, b in zip(origins, origins[1:])
    ]
    deltas = [d for d in deltas if d > size * 0.5]
    return statistics.median(deltas) if deltas else size * 1.2


def add_text(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog, item: NewText) -> EditReport:
    if not item.text.strip():
        raise TextEditError("Text is empty.")
    if item.style.font == "original":
        raise TextEditError("Choose a font for new text.")
    plan = plan_fonts(doc, page, catalog, item.style, None)
    style = _style(item.style, None, plan, doc, page)
    angle = item.rotation % 360
    display_dir = {0: (1.0, 0.0), 90: (0.0, -1.0), 180: (-1.0, 0.0), 270: (0.0, 1.0)}.get(angle, (1.0, 0.0))
    direction = from_display_vector(page, display_dir)
    ascent = style.size * max(0.7, min(1.0, plan.chain.ascender()))
    top_left = from_display_point(page, (item.x, item.y))
    down = (-direction[1], direction[0])
    origin = (top_left.x + down[0] * ascent, top_left.y + down[1] * ascent)
    placed = _layout(plan.chain, item.text, style, origin, direction, item.width, style.size * item.line_height, item.align)
    write_lines(doc, page, placed, style, plan.chain)
    return _report(plan.chain)


def document_fonts(doc: fitz.Document) -> list[dict]:
    """Fonts available in the document that can be re-used for new text."""
    seen: dict[int, dict] = {}
    for page in doc:
        for xref, ext, ftype, basefont, *_ in page.get_fonts(full=True):
            if xref <= 0 or xref in seen:
                continue
            if pdfobj.get_key(doc, xref, fontres.TAG_KEY)[0] != "null":
                continue  # fonts we inserted ourselves are offered via the catalog
            analysed = fontres.analyze_font(doc, xref)
            if analysed is None or not analysed.reverse:
                continue
            seen[xref] = {
                "xref": xref,
                "name": fontres.clean_font_name(basefont),
                "type": ftype,
                "embedded": analysed.embedded,
                "subset": bool(fontres.SUBSET_PREFIX.match(basefont)),
                "glyphs": len(analysed.reverse),
                "chars": "".join(sorted(c for c in analysed.reverse if len(c) == 1))[:400],
            }
        if len(seen) > 200:
            break
    return sorted(seen.values(), key=lambda item: item["name"].lower())
