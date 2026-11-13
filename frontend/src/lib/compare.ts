import type { ChangeKind, CompareChange, ComparePair, CompareReport } from "../api/compareTypes";
import type { Rect } from "../api/types";

/* ---------------------------------------------------------------- filters */

/** What the user can switch on and off in the change list. */
export type FilterKey = "text" | "image" | "page";
export type Filters = Record<FilterKey, boolean>;

export const ALL_FILTERS: Filters = { text: true, image: true, page: true };

const FILTER_OF: Record<ChangeKind, FilterKey> = { text: "text", visual: "image", page: "page" };

export function filterOf(change: CompareChange): FilterKey {
  return FILTER_OF[change.kind];
}

export function allChanges(report: CompareReport | null): CompareChange[] {
  return report ? report.pairs.flatMap((pair) => pair.changes) : [];
}

export function visibleChanges(report: CompareReport | null, filters: Filters): CompareChange[] {
  return allChanges(report).filter((change) => filters[filterOf(change)]);
}

export function countByFilter(report: CompareReport | null): Record<FilterKey, number> {
  const counts: Record<FilterKey, number> = { text: 0, image: 0, page: 0 };
  for (const change of allChanges(report)) counts[filterOf(change)] += 1;
  return counts;
}

/* ---------------------------------------------------------------- summary */

export function summarize(changes: CompareChange[]): { changes: number; pages: number } {
  return { changes: changes.length, pages: new Set(changes.map((change) => change.pair)).size };
}

/** "12 changes across 5 pages" */
export function summaryText(changes: CompareChange[]): string {
  const { changes: n, pages: m } = summarize(changes);
  if (n === 0) return "No differences found";
  return `${n} change${n === 1 ? "" : "s"} across ${m} page${m === 1 ? "" : "s"}`;
}

/* ---------------------------------------------------------------- wording */

export function clip(text: string, max: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
}

export function changeLabel(change: CompareChange): string {
  if (change.kind === "visual") return "Image or layout";
  if (change.kind === "page") {
    if (change.type === "insert") return "Page added";
    if (change.type === "delete") return "Page removed";
    return "Page size";
  }
  if (change.type === "insert") return "Added";
  if (change.type === "delete") return "Deleted";
  return "Replaced";
}

export function changeDetail(change: CompareChange, max = 90): string {
  if (change.kind === "visual") return "This area looks different";
  if (change.kind === "page" && change.type === "resize") return `${change.oldText} → ${change.newText}`;
  if (change.type === "replace") return `${clip(change.oldText, max / 2)} → ${clip(change.newText, max / 2)}`;
  const text = change.type === "insert" ? change.newText : change.oldText;
  return text ? clip(text, max) : "Page without text";
}

/** Where the change is: "Page 3", or "Page 3 → 4" when the page moved to another number. */
export function pageRef(change: CompareChange): string {
  const a = change.pageA === null ? null : change.pageA + 1;
  const b = change.pageB === null ? null : change.pageB + 1;
  if (a !== null && b !== null) return a === b ? `Page ${a}` : `Page ${a} → ${b}`;
  return a !== null ? `Page ${a}` : `New page ${b}`;
}

export function pairTitle(pair: ComparePair): string {
  if (pair.pageA !== null && pair.pageB !== null) {
    return pair.pageA === pair.pageB ? `Page ${pair.pageA + 1}` : `Page ${pair.pageA + 1} → ${pair.pageB + 1}`;
  }
  return pair.pageA !== null ? `Page ${pair.pageA + 1} removed` : `Page ${(pair.pageB ?? 0) + 1} added`;
}

/* ---------------------------------------------------------------- navigation */

/** The change after (1) or before (-1) the active one, wrapping around. With none active: the first or last. */
export function stepChange(changes: CompareChange[], activeId: string | null, direction: 1 | -1): CompareChange | null {
  if (!changes.length) return null;
  const at = changes.findIndex((change) => change.id === activeId);
  if (at < 0) return direction === 1 ? changes[0] : changes[changes.length - 1];
  return changes[(at + direction + changes.length) % changes.length];
}

/* ---------------------------------------------------------------- layout */

export const ROW_HEADER = 26; // page captions above each pair of pages
export const ROW_GAP = 18;
export const PAD_TOP = 12;
export const PAD_X = 20;
export const COLUMN_GAP = 20;
export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 4;

export interface RowLayout {
  offsets: number[];
  heights: number[];
  total: number;
}

function pairPoints(pair: ComparePair): { width: number; height: number } {
  const sizes = [pair.sizeA, pair.sizeB].filter((size): size is [number, number] => size !== null);
  return {
    width: Math.max(0, ...sizes.map((size) => size[0])),
    height: Math.max(0, ...sizes.map((size) => size[1])),
  };
}

/** Both documents scroll as one: a row holds a page pair and is as tall as the taller page. */
export function rowLayout(pairs: ComparePair[], zoom: number): RowLayout {
  const offsets: number[] = [];
  const heights: number[] = [];
  let y = PAD_TOP;
  for (const pair of pairs) {
    const height = ROW_HEADER + pairPoints(pair).height * zoom;
    offsets.push(y);
    heights.push(height);
    y += height + ROW_GAP;
  }
  return { offsets, heights, total: y + PAD_TOP };
}

/** Width of one side's column: the widest page of either document. */
export function columnWidth(pairs: ComparePair[], zoom: number): number {
  return Math.max(0, ...pairs.map((pair) => pairPoints(pair).width)) * zoom;
}

/** The first and last row (inclusive) that intersect the viewport, widened by ``margin`` pixels. */
export function visibleRange(layout: RowLayout, scrollTop: number, viewportHeight: number, margin: number): [number, number] {
  const top = scrollTop - margin;
  const bottom = scrollTop + viewportHeight + margin;
  let first = -1;
  let last = -1;
  for (let i = 0; i < layout.offsets.length; i++) {
    const end = layout.offsets[i] + layout.heights[i];
    if (end >= top && layout.offsets[i] <= bottom) {
      if (first < 0) first = i;
      last = i;
    }
  }
  return first < 0 ? [0, -1] : [first, last];
}

/** The zoom at which both columns fit the viewport width. */
export function fitZoom(pairs: ComparePair[], viewportWidth: number): number {
  const widest = Math.max(0, ...pairs.map((pair) => pairPoints(pair).width));
  if (!widest) return 1;
  const available = viewportWidth - PAD_X * 2 - COLUMN_GAP;
  return clampZoom(available / (widest * 2));
}

export function clampZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

/** Images are requested in 1/8 steps so the server's render cache stays small. */
export function renderScale(zoom: number, devicePixelRatio = 1): number {
  const dpr = Math.min(devicePixelRatio || 1, 3);
  return Math.min(8, Math.max(0.125, Math.round(zoom * dpr * 8) / 8));
}

/* ---------------------------------------------------------------- highlights */

export type Tone = "delete" | "insert" | "replace-old" | "replace-new" | "visual" | "page-insert" | "page-delete";
export type Side = "a" | "b";

export interface Highlight {
  key: string;
  changeId: string;
  rect: Rect;
  tone: Tone;
  /** An insertion point or deletion point: a zero-width rectangle drawn as a thin bar. */
  marker: boolean;
  active: boolean;
}

function boxes(change: CompareChange, rects: Rect[], tone: Tone, activeId: string | null, marker = false): Highlight[] {
  return rects.map((rect, index) => ({
    key: `${change.id}:${tone}:${index}`,
    changeId: change.id,
    rect,
    tone,
    marker,
    active: change.id === activeId,
  }));
}

/** What to draw over one side's page for the given changes: red on the original, green on the revised version. */
export function highlightsFor(changes: CompareChange[], side: Side, activeId: string | null): Highlight[] {
  const result: Highlight[] = [];
  for (const change of changes) {
    const own = side === "a" ? change.rectsA : change.rectsB;
    if (change.kind === "visual") {
      result.push(...boxes(change, own, "visual", activeId));
    } else if (change.kind === "page") {
      if (change.type === "insert" && side === "b") result.push(...boxes(change, own, "page-insert", activeId));
      if (change.type === "delete" && side === "a") result.push(...boxes(change, own, "page-delete", activeId));
    } else if (change.type === "replace") {
      result.push(...boxes(change, own, side === "a" ? "replace-old" : "replace-new", activeId));
    } else if (change.type === "delete") {
      const where = side === "a" ? change.rectsA : change.anchorB ? [change.anchorB] : [];
      result.push(...boxes(change, where, "delete", activeId, side === "b"));
    } else {
      const where = side === "b" ? change.rectsB : change.anchorA ? [change.anchorA] : [];
      result.push(...boxes(change, where, "insert", activeId, side === "a"));
    }
  }
  return result;
}

const MARKER_WIDTH = 3; // pixels

/** CSS box of a highlight on a page shown at ``zoom``. */
export function highlightBox(highlight: Highlight, zoom: number): { left: number; top: number; width: number; height: number } {
  const [x0, y0, x1, y1] = highlight.rect;
  if (highlight.marker) return { left: x0 * zoom - MARKER_WIDTH / 2, top: y0 * zoom, width: MARKER_WIDTH, height: Math.max(1, (y1 - y0) * zoom) };
  return { left: x0 * zoom, top: y0 * zoom, width: Math.max(2, (x1 - x0) * zoom), height: Math.max(2, (y1 - y0) * zoom) };
}

/* ---------------------------------------------------------------- scrolling */

/** The rectangle to bring into view for a change (the revised side first). */
export function focusRect(change: CompareChange): Rect | null {
  return change.rectsB[0] ?? change.rectsA[0] ?? change.anchorB ?? change.anchorA;
}

/** Scroll position that shows the change roughly a third of the way down the viewport. */
export function scrollTarget(layout: RowLayout, change: CompareChange, zoom: number, viewportHeight: number): number {
  const top = layout.offsets[change.pair];
  if (top === undefined) return 0;
  const rect = focusRect(change);
  const y = change.kind === "page" || !rect ? 0 : rect[1] * zoom;
  return Math.max(0, top + (y ? ROW_HEADER + y - viewportHeight * 0.3 : -PAD_TOP));
}

/* ---------------------------------------------------------------- staleness */

/** The open document has changed since it was compared. */
export function isStale(report: CompareReport | null, documentVersion: string | undefined): boolean {
  return Boolean(report && documentVersion !== undefined && report.baseVersion !== documentVersion);
}
