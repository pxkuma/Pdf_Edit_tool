import type { EditReport, Span, TextBlock, TextStyle } from "../../api/types";
import { checkSpanFont } from "../../lib/fontPrompt";
import { ensureFace, findFace, useFonts, variantOf } from "../../lib/fonts";
import type { ActiveEdit, SpanDraft } from "../../store/editor";
import { AUTO_BOX, DEFAULT_PUSH, useEditor } from "../../store/editor";

export function draftFromSpan(span: Span): SpanDraft {
  return {
    font: "original",
    size: span.size,
    color: span.color,
    bold: span.bold,
    italic: span.italic,
    underline: span.underline ?? false,
    strike: span.strike ?? false,
    opacity: span.opacity,
    charSpacing: null, // null = keep the original spacing exactly
    hscale: span.hscale || 100,
    fitWidth: false,
    reflow: !span.ocr,
    ocrMode: "replace",
  };
}

/** Only send properties the user actually changed, so "original" stays exact. */
export function styleFromDraft(span: Span, draft: SpanDraft): Partial<TextStyle> {
  const style: Partial<TextStyle> = { font: draft.font, underline: draft.underline, strike: draft.strike };
  if (Math.abs(draft.size - span.size) > 0.01) style.size = draft.size;
  if (draft.color.toLowerCase() !== span.color.toLowerCase()) style.color = draft.color;
  if (draft.bold !== span.bold) style.bold = draft.bold;
  if (draft.italic !== span.italic) style.italic = draft.italic;
  if (Math.abs(draft.opacity - span.opacity) > 0.005) style.opacity = draft.opacity;
  if (draft.charSpacing !== null) style.char_spacing = draft.charSpacing;
  if (Math.abs(draft.hscale - (span.hscale || 100)) > 0.01) style.hscale = draft.hscale;
  return style;
}

export function draftChanged(span: Span, draft: SpanDraft): boolean {
  const style = styleFromDraft(span, draft);
  return (
    draft.font !== "original" ||
    Object.keys(style).length > 3 ||
    draft.underline !== (span.underline ?? false) ||
    draft.strike !== (span.strike ?? false) ||
    draft.fitWidth
  );
}

/** The installed face used to preview a draft in the browser. */
export function previewFace(span: Span, draft: SpanDraft): string | null {
  const families = useFonts.getState().families;
  const baseId = draft.font.startsWith("face:") ? draft.font.slice(5) : span.face;
  const found = findFace(families, baseId);
  if (!found) return baseId;
  return variantOf(found.family, draft.bold, draft.italic).id;
}

export function preloadFace(faceId: string | null): void {
  void ensureFace(faceId);
}

export function blockText(block: TextBlock): string {
  const width = block.bbox[2] - block.bbox[0];
  return block.lines
    .map((line, index) => {
      const text = line.spans.map((s) => s.text).join("").replace(/\s+$/, "");
      const lineWidth = line.bbox[2] - line.bbox[0];
      const last = index === block.lines.length - 1;
      const hardBreak = !last && (lineWidth < width * 0.72 || /[:.;!?]$/.test(text) && lineWidth < width * 0.9);
      return text + (last ? "" : hardBreak ? "\n" : " ");
    })
    .join("");
}

export function beginSpanEdit(page: number, span: Span): ActiveEdit {
  const edit: ActiveEdit = { mode: "span", page, span, draft: draftFromSpan(span), align: "left" };
  preloadFace(span.face);
  void checkSpanFont(span);
  return edit;
}

/** Median distance between the baselines of a block's lines (points). */
export function lineStep(block: TextBlock, size: number): number {
  const baselines = block.lines.filter((l) => l.spans.length).map((l) => l.spans[0].origin[1]);
  const deltas = baselines
    .slice(1)
    .map((y, i) => y - baselines[i])
    .filter((d) => d > size * 0.5)
    .sort((a, b) => a - b);
  return deltas.length ? deltas[Math.floor(deltas.length / 2)] : size * 1.2;
}

export interface BlockEditOptions {
  typing?: boolean;
  uniform?: boolean;
  pressedAt?: number;
}

export function beginBlockEdit(page: number, block: TextBlock, text?: string, options: BlockEditOptions = {}): ActiveEdit | null {
  const spans = block.lines.flatMap((l) => l.spans);
  if (!spans.length) return null;
  const main = spans.reduce((a, b) => (b.text.length > a.text.length ? b : a));
  preloadFace(main.face);
  void checkSpanFont(main);
  return {
    mode: "block",
    page,
    span: main,
    blockId: block.id,
    boxSpanIds: spans.map((s) => s.id),
    boxSpans: spans,
    boxLines: block.lines.filter((l) => l.spans.some((s) => s.text.trim())).map((l) => l.bbox),
    typing: options.typing ?? true,
    uniform: options.uniform ?? true,
    pressedAt: options.pressedAt,
    blockBbox: block.bbox,
    blockText: text ?? blockText(block),
    lineStep: lineStep(block, main.size),
    lineHeight: null,
    box: AUTO_BOX,
    lineCount: block.lines.filter((l) => l.spans.some((s) => s.text.trim())).length || 1,
    push: DEFAULT_PUSH,
    draft: draftFromSpan(main),
    align: "left",
  };
}

export function reportEdit(report: EditReport | undefined): void {
  if (!report) return;
  const { toast } = useEditor.getState();
  if (report.push_skipped?.length) {
    const counts = report.push_skipped.reduce<Record<string, number>>((acc, k) => ({ ...acc, [k]: (acc[k] ?? 0) + 1 }), {});
    const list = Object.entries(counts).map(([kind, n]) => `${n} ${kind}${n > 1 ? "s" : ""}`).join(", ");
    toast(`Could not move ${list}; ${report.push_skipped.length > 1 ? "they stay" : "it stays"} in place.`, "warning");
  }
  if (report.missing_chars.length) {
    toast(`No installed font contains: ${report.missing_chars.join(" ")} — those characters were skipped.`, "warning");
  } else if (!report.exact_font && report.fonts_used.length > 1) {
    const [original, ...others] = report.fonts_used;
    const family = original.split(/[-,]/)[0].toLowerCase().replace(/[^a-z0-9]/g, "");
    const same = others.every((name) => name.toLowerCase().replace(/[^a-z0-9]/g, "").startsWith(family));
    if (!same) {
      toast(`Some characters are not in the embedded font subset, so ${others.join(", ")} was used for them.`, "info");
    }
  }
}
