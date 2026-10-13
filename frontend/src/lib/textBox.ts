/**
 * Geometry of editable text boxes (page points, display space).
 *
 * A box is auto-width by default: it keeps its original width for shorter text
 * and grows into the free space beside it for longer text, so a longer name on a
 * single line never drops onto a second line while there is room. Only when the
 * free space runs out (or the user fixes the width) does the text wrap.
 */
import type { Rect, TextBlock, TextLine } from "../api/types";

export type Align = "left" | "center" | "right" | "justify";
export type SideHandle = "e" | "w";
export type CornerHandle = "se" | "sw";

export interface HBox {
  x: number;
  width: number;
}

export interface FreeSpan {
  left: number;
  right: number;
}

const MIN_WIDTH = 12;
const GAP = 4; // keep this far away from neighbouring text
const MIN_SIZE = 1;
const MAX_SIZE = 500;

function overlapsVertically(a: Rect, b: Rect): boolean {
  const overlap = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
  return overlap > Math.min(a[3] - a[1], b[3] - b[1]) * 0.25;
}

/** Horizontal room around ``box``: up to the nearest text on the same lines, else the page margin. */
export function freeSpan(
  box: Rect,
  blocks: { id: string; bbox: Rect }[],
  excludeId: string | null,
  page: { width: number },
): FreeSpan {
  const others = blocks.filter((b) => b.id !== excludeId);
  const margin = Math.max(18, Math.min(72, ...blocks.map((b) => b.bbox[0])));
  let right = page.width - margin;
  let left = margin;
  for (const { bbox } of others) {
    if (!overlapsVertically(box, bbox)) continue;
    if (bbox[0] >= box[2] - 1) right = Math.min(right, bbox[0] - GAP);
    if (bbox[2] <= box[0] + 1) left = Math.max(left, bbox[2] + GAP);
  }
  return { left: Math.min(left, box[0]), right: Math.max(right, box[2]) };
}

/** Auto-width box for text whose widest line is ``natural`` points wide. */
export function autoBox(original: Rect, natural: number, free: FreeSpan, align: Align): HBox {
  const [x0, , x1] = original;
  const base = x1 - x0;
  const wanted = Math.max(base, Math.ceil(natural + 2));
  if (align === "right") {
    const width = Math.min(wanted, x1 - free.left);
    return { x: x1 - width, width };
  }
  if (align === "center") {
    const centre = (x0 + x1) / 2;
    const half = Math.min(wanted / 2, centre - free.left, free.right - centre);
    return { x: centre - half, width: half * 2 };
  }
  return { x: x0, width: Math.min(wanted, free.right - x0) };
}

/** Drag a side handle by ``dx`` points. */
export function widenBox(box: HBox, handle: SideHandle, dx: number): HBox {
  if (handle === "e") return { x: box.x, width: Math.max(MIN_WIDTH, box.width + dx) };
  const width = Math.max(MIN_WIDTH, box.width - dx);
  return { x: box.x + box.width - width, width };
}

/** Drag a corner handle by ``dx`` points: scales the text (size and box) proportionally. */
export function scaleBox(box: HBox, size: number, handle: CornerHandle, dx: number): { box: HBox; size: number } {
  const grow = handle === "se" ? dx : -dx;
  const raw = (box.width + grow) / box.width;
  const next = Math.round(Math.min(MAX_SIZE, Math.max(MIN_SIZE, size * raw)) * 2) / 2;
  const factor = next / size;
  const width = Math.max(MIN_WIDTH, box.width * factor);
  return { size: next, box: handle === "se" ? { x: box.x, width } : { x: box.x + box.width - width, width } };
}

const canvas = typeof document !== "undefined" ? document.createElement("canvas") : null;

/** Width in points of the widest line of ``text`` rendered with a CSS ``font`` at 1 px = 1 pt. */
export function naturalWidth(text: string, font: string, letterSpacing = 0): number {
  const ctx = canvas?.getContext("2d");
  const lines = text.split("\n");
  if (!ctx) return Math.max(...lines.map((l) => l.length)) * 7;
  ctx.font = font;
  return Math.max(
    0,
    ...lines.map((line) => ctx.measureText(line).width + Math.max(0, line.length - 1) * letterSpacing),
  );
}

const baseline = (line: TextLine): number => line.spans[0]?.origin[1] ?? line.bbox[3];
const lineSize = (line: TextLine): number => line.spans[0]?.size ?? line.bbox[3] - line.bbox[1];

function sharesRow(line: TextLine, others: TextLine[]): boolean {
  const tolerance = lineSize(line) * 0.3;
  return others.some((other) => other !== line && Math.abs(baseline(other) - baseline(line)) < tolerance);
}

function unionRect(rects: Rect[]): Rect {
  return [
    Math.min(...rects.map((r) => r[0])),
    Math.min(...rects.map((r) => r[1])),
    Math.max(...rects.map((r) => r[2])),
    Math.max(...rects.map((r) => r[3])),
  ];
}

/**
 * The lines of ``block`` that form one text box with the line ``lineId``.
 *
 * MuPDF often puts a label and its value, or the cells of a table row, into one
 * block. Those must not be stacked into a paragraph: a line that shares its
 * baseline with another one is a box on its own. Otherwise the box is the run of
 * neighbouring lines that overlap horizontally and are spaced like a paragraph.
 */
export function textBoxLines(block: TextBlock, lineId: string): TextBlock {
  const lines = block.lines.filter((l) => l.spans.length);
  const clicked = lines.find((l) => l.id === lineId);
  if (!clicked) return block;
  const single = (l: TextLine) => !sharesRow(l, lines);
  let group = [clicked];
  if (single(clicked)) {
    const sorted = [...lines].sort((a, b) => baseline(a) - baseline(b));
    const at = sorted.indexOf(clicked);
    const joins = (a: TextLine, b: TextLine) => {
      const range = unionRect(group.map((l) => l.bbox));
      const overlaps = Math.min(range[2], b.bbox[2]) - Math.max(range[0], b.bbox[0]) > 0;
      return single(b) && overlaps && Math.abs(baseline(b) - baseline(a)) < lineSize(a) * 2.2;
    };
    for (let i = at - 1; i >= 0 && joins(sorted[i + 1], sorted[i]); i--) group = [sorted[i], ...group];
    for (let i = at + 1; i < sorted.length && joins(sorted[i - 1], sorted[i]); i++) group = [...group, sorted[i]];
  }
  if (group.length === lines.length) return block;
  return { id: `${block.id}:${group[0].id}`, bbox: unionRect(group.map((l) => l.bbox)), lines: group };
}
