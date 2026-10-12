import type { CSSProperties } from "react";
import type { Point, Rect } from "../api/types";

export function normRect(a: Point, b: Point): Rect {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}

export function rectWidth(r: Rect): number {
  return r[2] - r[0];
}

export function rectHeight(r: Rect): number {
  return r[3] - r[1];
}

export function union(a: Rect, b: Rect): Rect {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
}

export function contains(r: Rect, p: Point, pad = 0): boolean {
  return p[0] >= r[0] - pad && p[0] <= r[2] + pad && p[1] >= r[1] - pad && p[1] <= r[3] + pad;
}

export function translate(r: Rect, dx: number, dy: number): Rect {
  return [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy];
}

export function cssRect(r: Rect, zoom: number): CSSProperties {
  return { left: r[0] * zoom, top: r[1] * zoom, width: (r[2] - r[0]) * zoom, height: (r[3] - r[1]) * zoom };
}

export type Handle = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";

export function resizeRect(r: Rect, handle: Handle, dx: number, dy: number, min = 4): Rect {
  let [x0, y0, x1, y1] = r;
  if (handle.includes("w")) x0 = Math.min(x0 + dx, x1 - min);
  if (handle.includes("e")) x1 = Math.max(x1 + dx, x0 + min);
  if (handle.includes("n")) y0 = Math.min(y0 + dy, y1 - min);
  if (handle.includes("s")) y1 = Math.max(y1 + dy, y0 + min);
  return [x0, y0, x1, y1];
}

/** Merge word boxes on the same visual line into one rectangle per line. */
export function mergeLineRects(rects: Rect[]): Rect[] {
  const sorted = [...rects].sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  const lines: Rect[] = [];
  for (const rect of sorted) {
    const last = lines[lines.length - 1];
    const sameLine = last && Math.abs((last[1] + last[3]) / 2 - (rect[1] + rect[3]) / 2) < (rect[3] - rect[1]) * 0.5;
    if (last && sameLine) lines[lines.length - 1] = union(last, rect);
    else lines.push(rect);
  }
  return lines;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
