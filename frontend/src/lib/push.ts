/**
 * Which content moves when a text box grows (page points, display space).
 *
 * Like a document flow, but explicit: everything below the box that overlaps
 * its column moves, and so does everything below a moving item in *its*
 * column (a full-width rule takes the content under it along). Footers stay
 * by default. The user can pin or include any item; the editor previews the
 * result live and sends exactly that list to the server.
 */
import type { PageModel, Rect } from "../api/types";

export type PushKind = "text" | "drawing" | "image" | "field" | "annot";
export type PushScope = "column" | "page";

export interface PushCandidate {
  key: string;
  kind: PushKind;
  bbox: Rect;
  xref?: number;
}

export interface PushOptions {
  scope: PushScope;
  overrides: Record<string, boolean>; // true = move, false = keep in place
}

export interface PushSelection {
  moving: PushCandidate[];
  kept: PushCandidate[]; // below the box but staying (clickable to include)
}

const FOOTER_ZONE = 0.92; // items starting this far down the page are footers
const MOVABLE_ANNOTS = new Set(["Text", "FreeText", "Square", "Circle", "Stamp", "FileAttachment"]);

/** Everything on the page that could move, except the box's own spans. */
export function pushCandidates(model: PageModel, boxSpanIds: ReadonlySet<string>): PushCandidate[] {
  const items: PushCandidate[] = [];
  for (const block of model.text.blocks) {
    for (const line of block.lines) {
      if (line.spans.some((s) => boxSpanIds.has(s.id)) || !line.spans.some((s) => s.text.trim())) continue;
      items.push({ key: `t:${line.id}`, kind: "text", bbox: line.bbox });
    }
  }
  (model.drawings ?? []).forEach((bbox, i) => items.push({ key: `d:${i}`, kind: "drawing", bbox }));
  model.images.forEach((img, i) => {
    if (img.xref > 0) items.push({ key: `i:${img.xref}:${i}`, kind: "image", bbox: img.bbox, xref: img.xref });
  });
  for (const field of model.fields) items.push({ key: `f:${field.xref}`, kind: "field", bbox: field.rect, xref: field.xref });
  for (const annot of model.annotations) {
    if (MOVABLE_ANNOTS.has(annot.type)) items.push({ key: `a:${annot.xref}`, kind: "annot", bbox: annot.rect, xref: annot.xref });
  }
  return items;
}

const overlapX = (a: [number, number], b: Rect) => Math.min(a[1], b[2]) - Math.max(a[0], b[0]) > 1;

export function selectPush(
  candidates: PushCandidate[],
  box: Rect,
  columnX: [number, number],
  options: PushOptions,
  page: { width: number; height: number },
): PushSelection {
  const below = candidates.filter((c) => c.bbox[1] >= box[3] - 1).sort((a, b) => a.bbox[1] - b.bbox[1]);
  const movers: { x: [number, number]; top: number }[] = [{ x: columnX, top: box[1] }];
  const moving: PushCandidate[] = [];
  const kept: PushCandidate[] = [];
  for (const item of below) {
    const inFlow = options.scope === "page" || movers.some((m) => m.top <= item.bbox[1] && overlapX(m.x, item.bbox));
    const footer = item.bbox[1] > page.height * FOOTER_ZONE;
    const moves = options.overrides[item.key] ?? (inFlow && !footer);
    if (moves) {
      moving.push(item);
      movers.push({ x: [item.bbox[0], item.bbox[2]], top: item.bbox[1] });
    } else {
      kept.push(item);
    }
  }
  return { moving, kept };
}

export interface GrowthInput {
  rows: number; // lines the box has now
  lines: number; // lines it had
  step: number; // baseline distance now
  originalStep: number;
  size: number;
  originalSize: number;
}

/** How much taller (positive) or shorter the box got, in points. */
export function boxGrowth(g: GrowthInput): number {
  const now = Math.max(0, g.rows - 1) * g.step + g.size * 1.15;
  const before = Math.max(0, g.lines - 1) * g.originalStep + g.originalSize * 1.15;
  return now - before;
}

/** Keys of kept items that moved content would overlap after shifting by ``dy``. */
export function pushConflicts(moving: PushCandidate[], kept: PushCandidate[], dy: number): string[] {
  if (Math.abs(dy) < 0.05) return [];
  const hits = (a: Rect, b: Rect) =>
    Math.min(a[2], b[2]) - Math.max(a[0], b[0]) > 0.5 && Math.min(a[3] + dy, b[3]) - Math.max(a[1] + dy, b[1]) > 0.5;
  return kept.filter((k) => moving.some((m) => hits(m.bbox, k.bbox))).map((k) => k.key);
}
