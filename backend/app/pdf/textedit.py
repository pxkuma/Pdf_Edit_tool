"""High level text editing: replace spans, reflow paragraphs, add new text."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace

import pymupdf as fitz

from . import decor, extract, fontres, ocr, pdfobj, push, textstate
from .fonts import FontCatalog, FontFace, style_from_name
from .geometry import (
    from_display_point,
    from_display_vector,
    hex_to_rgb,
    shrink_for_redaction,
)
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
    underline: bool | None = None  # None: keep what the text has
    strike: bool | None = None
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
    ocr_mode: str = "replace"  # OCR'd (invisible) text: "replace" in the image, or "hidden" layer only


@dataclass(frozen=True)
class BlockEdit:
    bbox: tuple[float, float, float, float]
    text: str
    style: StyleRequest = field(default_factory=StyleRequest)
    align: str = "left"
    line_height: float | None = None
    width: float | None = None  # box width the lines are aligned in (None: original block)
    max_width: float | None = None  # wrap limit for auto-width boxes (None: ``width``)
    dx: float = 0.0  # move, display space
    dy: float = 0.0
    push: push.PushRequest | None = None  # content below that moves with the box


# Browser and PDF font metrics differ by a fraction of a percent: never push the
# last word of a line that visibly fits in the box onto the next line.
WRAP_TOLERANCE = 1.01


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
    max_width: float | None = None  # wrap limit for auto-width boxes (None: ``width``)


@dataclass(frozen=True)
class EditReport:
    fonts_used: list[str]
    missing_chars: list[str]
    exact_font: bool
    pushed: int = 0  # objects moved below a text box
    push_skipped: list[str] = field(default_factory=list)


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
    drop_fake_bold: bool = False  # the text was bolded by stroking: stop doing that
    drop_fake_italic: bool = False  # the text was slanted by its matrix: straighten it


def plan_fonts(
    doc: fitz.Document,
    page: fitz.Page,
    catalog: FontCatalog,
    request: StyleRequest,
    span: dict | None,
) -> _FontPlan:
    base = _span_flags(span) if span else {"bold": False, "italic": False, "serif": False, "mono": False}
    fake_bold, fake_italic = extract.synthetic_style(span) if span else (False, False)
    shown_bold, shown_italic = base["bold"] or fake_bold, base["italic"] or fake_italic
    bold = shown_bold if request.bold is None else request.bold
    italic = shown_italic if request.italic is None else request.italic
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
    drop_bold, drop_italic = fake_bold and not bold, fake_italic and not italic
    variant = _real_variant(catalog, font_name, bold, italic) if (bold, italic) != (base["bold"], base["italic"]) else None
    if embedded is not None and (variant is not None or (base["bold"] and not bold) or (base["italic"] and not italic)):
        # The embedded font cannot lose (or gain) its own weight/slant: use the matching face.
        face = variant or substitute
        return _FontPlan(FontChain.build(catalog, None, face), bold and not (face and face.bold),
                         italic and not (face and face.italic), fake_bold, fake_italic)
    chain = FontChain.build(catalog, embedded, substitute)
    if embedded is None:
        return _FontPlan(chain, False, False, drop_bold, drop_italic)
    return _FontPlan(chain, bold and not shown_bold, italic and not shown_italic, drop_bold, drop_italic)


def _real_variant(catalog: FontCatalog, font_name: str, bold: bool, italic: bool) -> FontFace | None:
    """The installed face of the text's own family in the wanted weight/slant, if there is one."""
    family = catalog.exact_family(font_name)
    face = catalog.pick_variant(family, bold, italic) if family else None
    return face if face is not None and face.bold == bold and face.italic == italic else None


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
        underline=bool(request.underline),
        strike=bool(request.strike),
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
        underline=bool(request.underline),
        strike=bool(request.strike),
        char_spacing=record.page_char_spacing * scale if request.char_spacing is None else request.char_spacing,
        hscale=max(10.0, min(400.0, request.hscale or record.effective_hscale)),
        word_spacing=record.page_word_spacing * scale,
        rise=record.page_rise * scale,
        skew=0.0 if plan.drop_fake_italic else record.skew,
        render_mode=record.render_mode - 2 if plan.drop_fake_bold and record.render_mode in (2, 6) else record.render_mode,
        line_width=None if plan.drop_fake_bold else record.line_width * scale,
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


def _rebind(job: _WriteJob, doc: fitz.Document, page: fitz.Page) -> None:
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
                 graphics: int = fitz.PDF_REDACT_LINE_ART_NONE,
                 text: int = fitz.PDF_REDACT_TEXT_REMOVE) -> None:
    """Apply redactions for ``rects`` without applying pre-existing redact annots."""
    pending = []
    for annot in list(page.annots(types=[fitz.PDF_ANNOT_REDACT]) or []):
        pending.append((fitz.Rect(annot.rect), annot.info))
        page.delete_annot(annot)
    for rect in rects:
        if not rect.is_empty:
            page.add_redact_annot(rect, fill=fill)
    page.apply_redactions(images=images, graphics=graphics, text=text)
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
    direction: tuple[float, float] = (1.0, 0.0)


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
    requests: list[StyleRequest] | None = None,
) -> list[tuple[dict, _WriteJob]]:
    """Shift the spans following an edited span along the line by ``delta`` points.

    Returns an empty list when any follower cannot be rewritten with its exact
    original font (we never degrade untouched text just to close a gap).
    """
    jobs = []
    for i, span in enumerate(followers):
        job = _span_job(doc, page, catalog, span, span["text"], requests[i] if requests else StyleRequest())
        embedded = job.chain.embedded
        primary = span.get("primary_text", span["text"])
        if embedded is None or job.chain.missing or embedded.coverage(primary) < 1.0:
            return []
        job.origin = (job.origin[0] + direction[0] * delta, job.origin[1] + direction[1] * delta)
        jobs.append((span, job))
    return jobs


def _with_decorations(request: StyleRequest, found: dict[str, list[dict]]) -> StyleRequest:
    """Underline/strike left unset keep what the text already has."""
    return replace(
        request,
        underline=bool(found["underline"]) if request.underline is None else request.underline,
        strike=bool(found["strike"]) if request.strike is None else request.strike,
    )


def _merge_found(items: list[dict[str, list[dict]]]) -> dict[str, list[dict]]:
    return {kind: [path for found in items for path in found[kind]] for kind in ("underline", "strike")}


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
    record = span.get("record")
    if record is not None and record.render_mode in (3, 7) and edit.ocr_mode == "replace":
        return _replace_scanned(doc, page, catalog, edit, span, direction)
    rules = decor.page_rules(page)
    found_main = decor.for_run(span, line["bbox"], direction, rules)
    main = _span_job(doc, page, catalog, span, edit.text, _with_decorations(edit.style, found_main), edit.fit_width)
    moved = bool(edit.dx or edit.dy)
    if moved:
        move = _display_delta(page, edit.dx, edit.dy)
        main.origin = (main.origin[0] + move[0], main.origin[1] + move[1])
    followers: list[tuple[dict, _WriteJob]] = []
    if edit.reflow and not moved and not edit.fit_width:
        delta = line_width(main.glyphs, main.style) - _advance(span, direction)
        if abs(delta) > 0.05:
            candidates = _following_runs(runs, index, direction)
            found = [decor.for_run(c, line["bbox"], direction, rules) for c in candidates]
            requests = [_with_decorations(StyleRequest(), f) for f in found]
            followers = _reflow_jobs(doc, page, catalog, candidates, delta, direction, requests)
            found_main = _merge_found([found_main] + found[:len(followers)])
    rects = [shrink_for_redaction(fitz.Rect(s["bbox"]), direction) for s in [span] + [f[0] for f in followers]]
    redact_areas(page, rects)
    decor.erase(page, found_main["underline"] + found_main["strike"], redact_areas)
    for job in [main] + [f[1] for f in followers]:
        _rebind(job, doc, page)
        write_lines(doc, page, [PlacedLine(job.origin, direction, job.glyphs)], job.style, job.chain)
    return _report(main.chain)


def _replace_scanned(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog, edit: SpanEdit,
                     span: dict, direction: tuple[float, float]) -> EditReport:
    """Edit a word recognised by OCR: paint over it in the scan and draw real text.

    The background and ink colours are sampled from the image so the replacement
    blends in; the size and width follow the recognised word.
    """
    record = span["record"]
    rect = fitz.Rect(span["bbox"])
    sample = ocr.sample_colors(page, rect)
    background, ink = sample.background, sample.ink
    request = edit.style
    if request.bold is None:
        request = replace(request, bold=sample.looks_bold)
    font = request.font if request.font != "original" else ""
    if not font:
        face = catalog.substitute("Helvetica", bool(request.bold), bool(request.italic), False, False)
        font = f"face:{face.id}" if face else ""
    plan = plan_fonts(doc, page, catalog, replace(request, font=font), None)
    size = request.size or record.effective_size
    _check_size(size)
    style = TextStyle(
        size=size,
        color=hex_to_rgb(request.color, ink),
        opacity=1.0 if request.opacity is None else request.opacity,
        underline=bool(request.underline),
        strike=bool(request.strike),
        char_spacing=request.char_spacing or 0.0,
        # The invisible OCR layer is squeezed to Tesseract's tight ink boxes, so its
        # width scale is not a property of the scanned font: use natural width.
        hscale=max(10.0, min(400.0, request.hscale or 100.0)),
    )
    glyphs = plan.chain.encode(edit.text)
    if edit.fit_width and glyphs:
        natural = line_width(glyphs, style)
        if natural > 0:
            style = replace(style, hscale=max(30.0, min(300.0, style.hscale * rect.width / natural)))
    cover = rect + (-0.6, -0.6, 0.6, 0.6)
    redact_areas(page, [cover], fill=background, images=fitz.PDF_REDACT_IMAGE_PIXELS)
    origin = (span["origin"][0], span["origin"][1])
    if edit.dx or edit.dy:
        move = _display_delta(page, edit.dx, edit.dy)
        origin = (origin[0] + move[0], origin[1] + move[1])
    if edit.text.strip():
        write_lines(doc, page, [PlacedLine(origin, direction, glyphs)], style, plan.chain)
    return _report(plan.chain)


def _display_delta(page: fitz.Page, dx: float, dy: float) -> tuple[float, float]:
    a = from_display_point(page, (0.0, 0.0))
    b = from_display_point(page, (dx, dy))
    return (b.x - a.x, b.y - a.y)


def _wrap(chain: FontChain, text: str, style: TextStyle, max_width: float | None) -> list[tuple[list[Glyph], bool]]:
    """Return lines as (glyphs, is_paragraph_end)."""
    result: list[tuple[list[Glyph], bool]] = []
    max_width = max_width * WRAP_TOLERANCE + 0.5 if max_width else None
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
    wrap_width: float | None = None,
) -> list[PlacedLine]:
    """Lay text out in a box ``max_width`` wide; lines wrap at ``wrap_width`` (default: the box)."""
    down = (-direction[1], direction[0])
    placed = []
    lines = _wrap(chain, text, style, wrap_width or max_width)
    for index, (glyphs, paragraph_end) in enumerate(lines):
        width = line_width(glyphs, style)
        extra = 0.0
        if align == "justify" and max_width and not paragraph_end and width < max_width:
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
    found = extract.find_box_lines(page, edit.bbox)
    if found is None:
        raise TextEditError("The paragraph could not be found on the page any more.")
    _block, box_lines = found
    lines = [line for line in box_lines if any(s["text"].strip() for s in line["spans"])]
    if not lines:
        raise TextEditError("The paragraph contains no editable text.")
    direction = tuple(lines[0].get("dir", (1.0, 0.0)))
    tagged = extract.tagged_font_names(page)
    records = textstate.page_text_records(doc, page)
    first_runs = extract.attach_records(doc, extract.line_runs(lines[0], tagged), direction, records, tagged)
    first_span = max(first_runs, key=lambda s: len(s["text"]))
    rules = decor.page_rules(page)
    found = _merge_found([decor.for_run(run, line["bbox"], direction, rules)
                          for line in lines for run in extract.line_runs(line, tagged)])
    edit = replace(edit, style=_with_decorations(edit.style, found))
    plan = plan_fonts(doc, page, catalog, edit.style, first_span)
    style = _style(edit.style, first_span, plan, doc, page)
    step = _line_step(lines, direction, style.size, edit.line_height)
    origin = _block_start(lines, direction)
    if style.rise:
        origin = (origin[0] - direction[1] * style.rise, origin[1] + direction[0] * style.rise)
    if edit.dx or edit.dy:
        move = _display_delta(page, edit.dx, edit.dy)
        origin = (origin[0] + move[0], origin[1] + move[1])
    block_rect = fitz.Rect(lines[0]["bbox"])
    for line in lines[1:]:
        block_rect |= fitz.Rect(line["bbox"])
    width = edit.width or (block_rect.width if abs(direction[0]) >= abs(direction[1]) else block_rect.height) + 0.5
    wrap_width = max(edit.max_width, width) if edit.max_width else width
    placed = _layout(plan.chain, edit.text, style, origin, direction, width, step, edit.align, wrap_width)
    push_plan, push_jobs = _plan_push(doc, page, catalog, edit.push, lines, tagged, records)
    removal = [shrink_for_redaction(fitz.Rect(line["bbox"]), direction) for line in lines]
    if push_plan is not None:
        removal += [shrink_for_redaction(r, tuple(line.get("dir", (1.0, 0.0))))
                    for r, line in zip(push.text_removal_rects(push_plan), push_plan.lines)]
    redact_areas(page, removal)
    decor.erase(page, found["underline"] + found["strike"], redact_areas)
    if push_plan is not None:
        push.remove_graphics(page, push_plan, redact_areas)
        push.place_graphics(page, push_plan)
    if first_span.get("record") is not None:
        style = replace(style, **bind_resources(edit.style, first_span["record"], doc, page))
    write_lines(doc, page, placed, style, plan.chain)
    report = _report(plan.chain)
    if push_plan is None:
        return report
    for job in push_jobs:
        _rebind(job, doc, page)
        write_lines(doc, page, [PlacedLine(job.origin, job.direction, job.glyphs)], job.style, job.chain)
    push.place_copies(page, push_plan)
    return replace(report, pushed=push_plan.moved, push_skipped=push_plan.skipped)


def _plan_push(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog, request: push.PushRequest | None,
               box_lines: list[dict], tagged: set[str], records: list) -> tuple[push.PushPlan | None, list[_WriteJob]]:
    """Content below the box to move, and the text jobs that rewrite its lines in their own fonts."""
    if request is None or not request.items or request.is_identity:
        return None, []
    lines = [line for block in extract.page_dict(page).get("blocks", []) if block.get("type", 0) == 0
             for line in block["lines"]]
    push_plan = push.plan(doc, page, request, lines, box_lines)
    rules = decor.page_rules(page)
    jobs: list[_WriteJob] = []
    for line in push_plan.lines:
        direction = tuple(line.get("dir", (1.0, 0.0)))
        runs = extract.attach_records(doc, extract.line_runs(line, tagged), direction, records, tagged)
        for run in runs:  # underline/strike lines travel with their text
            found = decor.for_run(run, line["bbox"], direction, rules)
            push_plan.paths += [p for p in found["underline"] + found["strike"]
                                if not any(decor.same_path(p, q) for q in push_plan.paths)]
        line_jobs = _exact_jobs(doc, page, catalog, runs)
        if line_jobs is None:
            push_plan.copies.append(fitz.Rect(line["bbox"]))  # not rewritable exactly: copy it
            continue
        for job in line_jobs:
            moved = fitz.Point(job.origin) * push_plan.matrix
            job.origin = (moved.x, moved.y)
            job.direction = direction
        jobs.extend(line_jobs)
    return push_plan, jobs


def transform_objects(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog,
                      request: push.PushRequest) -> EditReport:
    """Move/resize page objects as themselves (text in its own fonts, paths, images)."""
    tagged = extract.tagged_font_names(page)
    records = textstate.page_text_records(doc, page)
    push_plan, jobs = _plan_push(doc, page, catalog, request, [], tagged, records)
    if push_plan is None or not (push_plan.moved or push_plan.copies):
        raise TextEditError("Nothing to move here.")
    removal = [shrink_for_redaction(fitz.Rect(line["bbox"]), tuple(line.get("dir", (1.0, 0.0))))
               for line in push_plan.lines]
    if removal:
        redact_areas(page, removal)
    push.remove_graphics(page, push_plan, redact_areas)
    push.place_graphics(page, push_plan)
    for job in jobs:
        _rebind(job, doc, page)
        write_lines(doc, page, [PlacedLine(job.origin, job.direction, job.glyphs)], job.style, job.chain)
    push.place_copies(page, push_plan)
    return EditReport([], [], True, push_plan.moved, push_plan.skipped)


def delete_objects(doc: fitz.Document, page: fitz.Page, items: tuple[push.PushItem, ...]) -> int:
    """Remove page objects (text lines with their decorations, paths, images, fields)."""
    lines = [line for block in extract.page_dict(page).get("blocks", []) if block.get("type", 0) == 0
             for line in block["lines"]]
    plan = push.plan(doc, page, push.PushRequest(0.0, items), lines, [])
    rules = decor.page_rules(page)
    tagged = extract.tagged_font_names(page)
    for line in plan.lines:
        direction = tuple(line.get("dir", (1.0, 0.0)))
        for run in extract.line_runs(line, tagged):
            found = decor.for_run(run, line["bbox"], direction, rules)
            plan.paths += [p for p in found["underline"] + found["strike"]
                           if not any(decor.same_path(p, q) for q in plan.paths)]
    if not (plan.lines or plan.paths or plan.images or plan.widgets or plan.annots):
        raise TextEditError("Nothing to delete here.")
    if plan.lines:
        redact_areas(page, [shrink_for_redaction(fitz.Rect(line["bbox"]), tuple(line.get("dir", (1.0, 0.0))))
                            for line in plan.lines])
    push.remove_graphics(page, plan, redact_areas)
    # Put back only the paths the removal caught by accident.
    push.place_graphics(page, replace(plan, paths=[], images=[], widgets=[], annots=[]))
    for widget in list(page.widgets() or []):
        if widget.xref in plan.widgets:
            page.delete_widget(widget)
    for annot in list(page.annots() or []):
        if annot.xref in plan.annots:
            page.delete_annot(annot)
    return plan.moved


def _exact_jobs(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog, runs: list[dict]) -> list[_WriteJob] | None:
    jobs = []
    for span in runs:
        if not span["text"]:
            continue
        job = _span_job(doc, page, catalog, span, span["text"], StyleRequest())
        embedded = job.chain.embedded
        primary = span.get("primary_text", span["text"])
        if embedded is None or job.chain.missing or embedded.coverage(primary) < 1.0:
            return None
        jobs.append(job)
    return jobs


def _block_start(lines: list[dict], direction: tuple[float, float]) -> tuple[float, float]:
    """Baseline origin of the first line, moved back to the block's leading edge.

    The text box starts where the leftmost line starts (along the text direction),
    so an indented first line does not indent every rewritten line.
    """
    first = lines[0]["spans"][0]["origin"]
    along = [line["spans"][0]["origin"][0] * direction[0] + line["spans"][0]["origin"][1] * direction[1]
             for line in lines]
    back = min(along) - (first[0] * direction[0] + first[1] * direction[1])
    return (first[0] + direction[0] * back, first[1] + direction[1] * back)


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
    wrap_width = max(item.max_width, item.width or 0.0) if item.max_width else None
    placed = _layout(plan.chain, item.text, style, origin, direction, item.width,
                     style.size * item.line_height, item.align, wrap_width)
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
