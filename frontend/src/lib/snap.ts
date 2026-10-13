/**
 * Smart guides for text boxes (page points, display space): while moving or
 * resizing, edges and centres snap to other text and to the page centre.
 */
import type { Rect } from "../api/types";

/** Snapping distance on screen (CSS px). */
export const SNAP_PX = 6;

/** Alt+arrow nudging: direction per key (Shift multiplies by 10). */
export const NUDGE: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

export interface SnapTargets {
  xs: number[];
  ys: number[];
}

export interface Guides {
  x?: number;
  y?: number;
}

export function snapTargets(rects: Rect[], page: { width: number; height: number }): SnapTargets {
  const xs = [page.width / 2];
  const ys = [page.height / 2];
  for (const [x0, y0, x1, y1] of rects) {
    xs.push(x0, x1, (x0 + x1) / 2);
    ys.push(y0, y1);
  }
  return { xs, ys };
}

function nearest(value: number, targets: number[], threshold: number): number | undefined {
  let best: number | undefined;
  for (const target of targets) {
    if (Math.abs(target - value) <= threshold && (best === undefined || Math.abs(target - value) < Math.abs(best - value))) {
      best = target;
    }
  }
  return best;
}

/** Snap a moving box: left edge, centre or right edge horizontally; top or bottom vertically. */
export function snapBox(
  box: { x: number; y: number; width: number; height: number },
  targets: SnapTargets,
  threshold: number,
): { x: number; y: number; guides: Guides } {
  let x = box.x;
  let y = box.y;
  const guides: Guides = {};
  let bestX = threshold + 1;
  for (const offset of [0, box.width / 2, box.width]) {
    const hit = nearest(box.x + offset, targets.xs, threshold);
    if (hit !== undefined && Math.abs(hit - (box.x + offset)) < bestX) {
      bestX = Math.abs(hit - (box.x + offset));
      x = hit - offset;
      guides.x = hit;
    }
  }
  let bestY = threshold + 1;
  for (const offset of [0, box.height]) {
    const hit = nearest(box.y + offset, targets.ys, threshold);
    if (hit !== undefined && Math.abs(hit - (box.y + offset)) < bestY) {
      bestY = Math.abs(hit - (box.y + offset));
      y = hit - offset;
      guides.y = hit;
    }
  }
  return { x, y, guides };
}

/** Snap one dragged edge (resizing). */
export function snapEdge(value: number, targets: number[], threshold: number): { value: number; guide: number | undefined } {
  const hit = nearest(value, targets, threshold);
  return { value: hit ?? value, guide: hit };
}
