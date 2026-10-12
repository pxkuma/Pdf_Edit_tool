"""Document wide tools: stamping, numbering, search/replace, redaction, metadata."""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass

import pymupdf as fitz

from . import extract
from .fonts import FontCatalog
from .geometry import from_display_point, from_display_rect, from_display_vector, hex_to_rgb, to_display_rect
from .textedit import SpanEdit, StyleRequest, TextEditError, edit_span, plan_fonts, redact_areas
from .textwriter import PlacedLine, TextStyle, line_width, write_lines

POSITIONS = {"top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"}
METADATA_KEYS = ("title", "author", "subject", "keywords", "creator", "producer")


class ToolError(ValueError):
    pass


def resolve_pages(doc: fitz.Document, spec: str | None) -> list[int]:
    """Parse "1-3,5,8-" (1-based, inclusive) into 0-based indices. Empty => all."""
    total = doc.page_count
    if not spec or not spec.strip() or spec.strip().lower() == "all":
        return list(range(total))
    pages: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        match = re.fullmatch(r"(\d*)-(\d*)|(\d+)", part)
        if not match:
            raise ToolError(f"Invalid page range '{part}'. Use e.g. 1-3,5")
        if match.group(3):
            start = end = int(match.group(3))
        else:
            start = int(match.group(1) or 1)
            end = int(match.group(2) or total)
        if start < 1 or end > total or start > end:
            raise ToolError(f"Page range '{part}' is outside 1-{total}.")
        pages.update(range(start - 1, end))
    return sorted(pages)


@dataclass(frozen=True)
class StampStyle:
    font: str = "face:"
    size: float = 48.0
    color: str = "#888888"
    opacity: float = 0.3
    bold: bool = False
    italic: bool = False


def _write_centered(doc: fitz.Document, page: fitz.Page, catalog: FontCatalog, text: str,
                    style: StampStyle, center: tuple[float, float], angle: float) -> None:
    request = StyleRequest(font=style.font, size=style.size, color=style.color, bold=style.bold,
                           italic=style.italic, opacity=style.opacity)
    plan = plan_fonts(doc, page, catalog, request, None)
    text_style = TextStyle(size=style.size, color=hex_to_rgb(style.color), opacity=style.opacity)
    glyphs = plan.chain.encode(text)
    if not glyphs:
        return
    width = line_width(glyphs, text_style)
    rad = math.radians(angle)
    display_dir = (math.cos(rad), -math.sin(rad))
    direction = from_display_vector(page, display_dir)
    up = (display_dir[1], -display_dir[0])  # perpendicular pointing up on screen
    cap = style.size * 0.35
    start_display = (
        center[0] - display_dir[0] * width / 2 - up[0] * cap,
        center[1] - display_dir[1] * width / 2 - up[1] * cap,
    )
    origin = from_display_point(page, start_display)
    write_lines(doc, page, [PlacedLine((origin.x, origin.y), direction, glyphs)], text_style, plan.chain)


def watermark(doc: fitz.Document, catalog: FontCatalog, pages: list[int], text: str, style: StampStyle,
              angle: float, layout: str) -> None:
    if not text.strip():
        raise ToolError("Watermark text is empty.")
    for index in pages:
        page = doc[index]
        w, h = page.rect.width, page.rect.height
        if layout == "tile":
            step_x, step_y = max(style.size * len(text) * 0.6, 120), max(style.size * 3, 80)
            y = step_y / 2
            row = 0
            while y < h + step_y:
                x = (step_x / 2) * (row % 2)
                while x < w + step_x:
                    _write_centered(doc, page, catalog, text, style, (x, y), angle)
                    x += step_x
                y += step_y
                row += 1
        else:
            _write_centered(doc, page, catalog, text, style, (w / 2, h / 2), angle)


def image_watermark(doc: fitz.Document, pages: list[int], data: bytes, scale: float, opacity: float) -> None:
    try:
        pix = fitz.Pixmap(data)
    except Exception as exc:  # noqa: BLE001
        raise ToolError("Unsupported watermark image.") from exc
    if max(pix.width, pix.height) > 2400:
        ratio = 2400 / max(pix.width, pix.height)
        pix = fitz.Pixmap(pix, int(pix.width * ratio), int(pix.height * ratio))
    if pix.colorspace and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if opacity < 0.999:
        if not pix.alpha:
            pix = fitz.Pixmap(pix, 1)
        current = bytes(pix.samples)[pix.n - 1 :: pix.n]
        pix.set_alpha(bytes(int(a * max(0.0, opacity)) for a in current))
    payload = pix.tobytes("png")
    for index in pages:
        page = doc[index]
        w, h = page.rect.width * scale, page.rect.height * scale
        ratio = min(w / pix.width, h / pix.height)
        iw, ih = pix.width * ratio, pix.height * ratio
        cx, cy = page.rect.width / 2, page.rect.height / 2
        rect = from_display_rect(page, (cx - iw / 2, cy - ih / 2, cx + iw / 2, cy + ih / 2))
        page.insert_image(rect, stream=payload, rotate=page.rotation, overlay=True)


def _fill_template(template: str, number: int, total: int, filename: str) -> str:
    return (
        template.replace("{n}", str(number))
        .replace("{total}", str(total))
        .replace("{date}", dt.date.today().isoformat())
        .replace("{filename}", filename)
    )


def header_footer(doc: fitz.Document, catalog: FontCatalog, pages: list[int], template: str, position: str,
                  margin: float, style: StampStyle, start_number: int, filename: str) -> None:
    if position not in POSITIONS:
        raise ToolError("Unknown position.")
    if not template.strip():
        raise ToolError("Text is empty.")
    total = len(pages) + start_number - 1
    vertical, horizontal = position.split("-")
    for offset, index in enumerate(pages):
        page = doc[index]
        text = _fill_template(template, start_number + offset, total, filename)
        request = StyleRequest(font=style.font, size=style.size, color=style.color, bold=style.bold, italic=style.italic)
        plan = plan_fonts(doc, page, catalog, request, None)
        text_style = TextStyle(size=style.size, color=hex_to_rgb(style.color), opacity=style.opacity)
        glyphs = plan.chain.encode(text)
        width = line_width(glyphs, text_style)
        w, h = page.rect.width, page.rect.height
        x = {"left": margin, "center": (w - width) / 2, "right": w - margin - width}[horizontal]
        y = margin + style.size * 0.8 if vertical == "top" else h - margin
        origin = from_display_point(page, (x, y))
        direction = from_display_vector(page, (1.0, 0.0))
        write_lines(doc, page, [PlacedLine((origin.x, origin.y), direction, glyphs)], text_style, plan.chain)


def search(doc: fitz.Document, query: str, limit: int = 2000) -> list[dict]:
    if not query.strip():
        return []
    hits = []
    for page in doc:
        for quad in page.search_for(query, quads=True):
            hits.append({"page": page.number, "rect": to_display_rect(page, quad.rect)})
            if len(hits) >= limit:
                return hits
    return hits


def replace_text(doc: fitz.Document, catalog: FontCatalog, query: str, replacement: str,
                 pages: list[int], match_case: bool, whole_word: bool) -> dict:
    if not query:
        raise ToolError("Search text is empty.")
    flags = 0 if match_case else re.IGNORECASE
    pattern = re.compile((r"\b%s\b" if whole_word else "%s") % re.escape(query), flags)
    replaced, skipped, changed = 0, 0, set()
    for index in pages:
        page = doc[index]
        total = len(pattern.findall(page.get_text()))
        page_replaced = 0
        for bbox, origin, text in _spans_matching(page, pattern):
            new_text, count = pattern.subn(lambda _m: replacement, text)
            try:
                edit_span(doc, page, catalog, SpanEdit(bbox, origin, text, new_text, StyleRequest()))
            except TextEditError:
                continue
            page_replaced += count
            changed.add(index)
        replaced += page_replaced
        skipped += max(0, total - page_replaced)
    return {"replaced": replaced, "skipped": skipped, "pages": sorted(changed)}


def _spans_matching(page: fitz.Page, pattern: re.Pattern) -> list[tuple]:
    """Spans containing a match, ordered right-to-left within lines so reflow stays valid."""
    model = extract.page_text_model(page)
    result = []
    for block in model["blocks"]:
        for line in block["lines"]:
            for span in reversed(line["spans"]):
                if pattern.search(span["text"]):
                    result.append((span["bbox"], span["origin"], span["text"]))
    return result


def redact(doc: fitz.Document, page: fitz.Page, rects: list[tuple], mode: str, color: str) -> None:
    """mode: 'redact' (remove everything, fill), 'whiteout' (remove text, fill), 'text' (remove text only)."""
    targets = [from_display_rect(page, r) for r in rects]
    targets = [r for r in targets if not r.is_empty and r.width > 0.5 and r.height > 0.5]
    if not targets:
        raise ToolError("Select an area first.")
    if mode == "redact":
        redact_areas(page, targets, fill=hex_to_rgb(color, (0, 0, 0)),
                     images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)
    elif mode == "whiteout":
        redact_areas(page, targets, fill=hex_to_rgb(color, (1, 1, 1)),
                     images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)
    elif mode == "text":
        redact_areas(page, targets, fill=False)
    else:
        raise ToolError("Unknown redaction mode.")


def redact_search(doc: fitz.Document, query: str, pages: list[int], color: str) -> dict:
    if not query.strip():
        raise ToolError("Search text is empty.")
    count, changed = 0, set()
    for index in pages:
        page = doc[index]
        rects = page.search_for(query)
        if rects:
            redact_areas(page, rects, fill=hex_to_rgb(color, (0, 0, 0)),
                         images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
            count += len(rects)
            changed.add(index)
    return {"redacted": count, "pages": sorted(changed)}


def get_metadata(doc: fitz.Document) -> dict:
    meta = doc.metadata or {}
    return {key: meta.get(key, "") or "" for key in METADATA_KEYS}


def set_metadata(doc: fitz.Document, values: dict) -> None:
    meta = dict(doc.metadata or {})
    for key in METADATA_KEYS:
        if key in values and values[key] is not None:
            meta[key] = str(values[key])[:1000]
    meta["modDate"] = fitz.get_pdf_now()
    doc.set_metadata(meta)


def get_toc(doc: fitz.Document) -> list[dict]:
    return [{"level": level, "title": title, "page": max(0, page - 1)} for level, title, page, *_ in doc.get_toc(simple=False)]


def set_toc(doc: fitz.Document, items: list[dict]) -> None:
    toc = []
    previous = 0
    for item in items:
        level = max(1, min(int(item.get("level", 1)), previous + 1))
        page = max(0, min(int(item.get("page", 0)), doc.page_count - 1))
        title = str(item.get("title", "")).strip()[:300] or "Untitled"
        toc.append([level, title, page + 1])
        previous = level
    doc.set_toc(toc)


@dataclass(frozen=True)
class ExportOptions:
    optimize: bool = True
    subset_fonts: bool = True
    compress_images: bool = False
    image_dpi: int = 150
    image_quality: int = 75
    flatten_annotations: bool = False
    flatten_forms: bool = False
    user_password: str = ""
    owner_password: str = ""
    allow_print: bool = True
    allow_copy: bool = True
    allow_modify: bool = True
    allow_annotate: bool = True
    remove_metadata: bool = False


def export_pdf(payload: bytes, options: ExportOptions) -> bytes:
    doc = fitz.open("pdf", payload)
    try:
        if options.flatten_annotations or options.flatten_forms:
            doc.bake(annots=options.flatten_annotations, widgets=options.flatten_forms)
        if options.subset_fonts:
            try:
                doc.subset_fonts()
            except Exception:  # noqa: BLE001 - subsetting is an optimisation only
                pass
        if options.compress_images:
            dpi = max(36, min(600, options.image_dpi))
            doc.rewrite_images(dpi_threshold=int(dpi * 1.3), dpi_target=dpi, quality=max(10, min(95, options.image_quality)))
        if options.remove_metadata:
            doc.set_metadata({})
            doc.del_xml_metadata()
        save_args: dict = {"garbage": 4 if options.optimize else 1, "deflate": True, "clean": options.optimize}
        if options.optimize:
            save_args.update(deflate_images=True, deflate_fonts=True, use_objstms=1)
        if options.user_password or options.owner_password:
            permissions = fitz.PDF_PERM_ACCESSIBILITY
            if options.allow_print:
                permissions |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
            if options.allow_copy:
                permissions |= fitz.PDF_PERM_COPY
            if options.allow_modify:
                permissions |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ASSEMBLE
            if options.allow_annotate:
                permissions |= fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM
            save_args.update(
                encryption=fitz.PDF_ENCRYPT_AES_256,
                user_pw=options.user_password,
                owner_pw=options.owner_password or options.user_password,
                permissions=permissions,
            )
        return doc.tobytes(**save_args)
    finally:
        doc.close()


def page_images(doc: fitz.Document, pages: list[int], dpi: int, fmt: str) -> list[tuple[str, bytes]]:
    dpi = max(36, min(600, dpi))
    fmt = "jpg" if fmt in ("jpg", "jpeg") else "png"
    out = []
    for index in pages:
        pix = doc[index].get_pixmap(dpi=dpi, alpha=False)
        data = pix.tobytes("jpeg", jpg_quality=90) if fmt == "jpg" else pix.tobytes("png")
        out.append((f"page-{index + 1:04d}.{fmt}", data))
    return out


def split(doc: fitz.Document, every: int) -> list[tuple[str, bytes]]:
    every = max(1, every)
    parts = []
    for start in range(0, doc.page_count, every):
        end = min(start + every, doc.page_count) - 1
        out = fitz.open()
        out.insert_pdf(doc, from_page=start, to_page=end)
        parts.append((f"pages-{start + 1:04d}-{end + 1:04d}.pdf", out.tobytes(garbage=3, deflate=True)))
        out.close()
    return parts
