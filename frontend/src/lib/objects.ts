/**
 * Page objects the editor can grab, Canva-style: text boxes, images and
 * vector graphics (rules, boxes, table grids). Page points, display space.
 */
import type { PageModel, Rect, TextBlock } from "../api/types";
import type { Handle } from "./geometry";
import { textBoxLines } from "./textBox";

export interface TextBox {
  key: string;
  block: TextBlock; // the box's lines (see textBoxLines)
  bbox: Rect;
  uniform: boolean; // one style throughout: can be retyped as a whole
  ocr: boolean;
}

export interface PageObject {
  key: string;
  kind: "image" | "drawing";
  bbox: Rect;
  hit: Rect; // grabbable area (thin rules get some thickness)
  xref?: number;
}

const MIN_HIT = 6;

export function textBoxes(model: PageModel): TextBox[] {
  const seen = new Set<string>();
  const boxes: TextBox[] = [];
  for (const block of model.text.blocks) {
    for (const line of block.lines) {
      const box = textBoxLines(block, line.id);
      if (seen.has(box.id)) continue;
      seen.add(box.id);
      const spans = box.lines.flatMap((l) => l.spans).filter((s) => s.text.trim());
      if (!spans.length) continue;
      const first = spans[0];
      const uniform = spans.every(
        (s) => s.font === first.font && Math.abs(s.size - first.size) < 0.05 && s.color === first.color && s.bold === first.bold && s.italic === first.italic,
      );
      boxes.push({ key: `tb:${box.id}`, block: box, bbox: box.bbox, uniform, ocr: spans.some((s) => s.ocr) });
    }
  }
  return boxes;
}

function grabbable(rect: Rect): Rect {
  const [x0, y0, x1, y1] = rect;
  const padX = Math.max(0, (MIN_HIT - (x1 - x0)) / 2);
  const padY = Math.max(0, (MIN_HIT - (y1 - y0)) / 2);
  return [x0 - padX, y0 - padY, x1 + padX, y1 + padY];
}

/** Drawings first (they usually sit behind), then images. */
export function pageObjects(model: PageModel): PageObject[] {
  const drawings = (model.drawings ?? []).map((bbox, i): PageObject => ({ key: `d:${i}:${bbox.join(",")}`, kind: "drawing", bbox, hit: grabbable(bbox) }));
  const images = model.images
    .filter((img) => img.editable && img.xref > 0)
    .map((img, i): PageObject => ({ key: `i:${img.xref}:${i}`, kind: "image", bbox: img.bbox, hit: grabbable(img.bbox), xref: img.xref }));
  return [...drawings, ...images];
}

export function moveRect(rect: Rect, dx: number, dy: number): Rect {
  return [rect[0] + dx, rect[1] + dy, rect[2] + dx, rect[3] + dy];
}

const MIN_SIZE = 2;

/** Resize from a handle; corners keep the proportions when ``keepAspect``. Never limited by the page. */
export function resizeObject(rect: Rect, handle: Handle, dx: number, dy: number, keepAspect: boolean): Rect {
  let [x0, y0, x1, y1] = rect;
  if (handle.includes("w")) x0 = Math.min(x0 + dx, x1 - MIN_SIZE);
  if (handle.includes("e")) x1 = Math.max(x1 + dx, x0 + MIN_SIZE);
  if (handle.includes("n")) y0 = Math.min(y0 + dy, y1 - MIN_SIZE);
  if (handle.includes("s")) y1 = Math.max(y1 + dy, y0 + MIN_SIZE);
  const corner = handle.length === 2;
  const w = rect[2] - rect[0];
  const h = rect[3] - rect[1];
  if (!corner || !keepAspect || w <= 0 || h <= 0) return [x0, y0, x1, y1];
  const scale = Math.max((x1 - x0) / w, (y1 - y0) / h);
  const nw = w * scale;
  const nh = h * scale;
  return [
    handle.includes("w") ? rect[2] - nw : rect[0],
    handle.includes("n") ? rect[3] - nh : rect[1],
    handle.includes("w") ? rect[2] : rect[0] + nw,
    handle.includes("n") ? rect[3] : rect[1] + nh,
  ];
}
