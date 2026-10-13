/**
 * The background colour behind text, sampled from the page rendering, so the
 * editing overlays (covers, inputs) blend in on coloured backgrounds instead of
 * showing white patches.
 */
import { useEffect, useMemo, useState } from "react";
import type { Rect } from "../api/types";

/** Most common colour (quantised) in RGBA pixel data. */
export function dominantColor(data: Uint8ClampedArray): string {
  const counts = new Map<number, { n: number; r: number; g: number; b: number }>();
  let best: { n: number; r: number; g: number; b: number } | null = null;
  for (let i = 0; i + 3 < data.length; i += 4) {
    const key = ((data[i] >> 3) << 10) | ((data[i + 1] >> 3) << 5) | (data[i + 2] >> 3);
    const entry = counts.get(key) ?? { n: 0, r: data[i], g: data[i + 1], b: data[i + 2] };
    entry.n += 1;
    counts.set(key, entry);
    if (!best || entry.n > best.n) best = entry;
  }
  return best ? `rgb(${best.r}, ${best.g}, ${best.b})` : "#ffffff";
}

const canvases = new Map<string, Promise<HTMLCanvasElement | null>>();

function pageCanvas(src: string): Promise<HTMLCanvasElement | null> {
  let promise = canvases.get(src);
  if (!promise) {
    promise = new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        if (!ctx) return resolve(null);
        ctx.drawImage(img, 0, 0);
        resolve(canvas);
      };
      img.onerror = () => resolve(null);
      img.src = src;
    });
    canvases.set(src, promise);
    if (canvases.size > 8) canvases.delete(canvases.keys().next().value as string);
  }
  return promise;
}

/** Sample the ring of pixels just around ``rect`` (page points). */
function sample(canvas: HTMLCanvasElement, rect: Rect, pageWidth: number): string {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return "#ffffff";
  const scale = canvas.width / pageWidth;
  const x0 = Math.max(0, Math.floor((rect[0] - 2) * scale));
  const y0 = Math.max(0, Math.floor((rect[1] - 2) * scale));
  const x1 = Math.min(canvas.width - 1, Math.ceil((rect[2] + 2) * scale));
  const y1 = Math.min(canvas.height - 1, Math.ceil((rect[3] + 2) * scale));
  if (x1 <= x0 || y1 <= y0) return "#ffffff";
  const rows = [ctx.getImageData(x0, y0, x1 - x0, 1).data, ctx.getImageData(x0, y1, x1 - x0, 1).data];
  const cols = [ctx.getImageData(x0, y0, 1, y1 - y0).data, ctx.getImageData(x1, y0, 1, y1 - y0).data];
  const all = new Uint8ClampedArray(rows.concat(cols).reduce((n, d) => n + d.length, 0));
  let offset = 0;
  for (const part of rows.concat(cols)) {
    all.set(part, offset);
    offset += part.length;
  }
  return dominantColor(all);
}

/** Background colours behind ``rects`` (white until the page rendering is ready). */
export function useBackgrounds(src: string | null, pageWidth: number, rects: Rect[]): string[] {
  const [canvas, setCanvas] = useState<HTMLCanvasElement | null>(null);
  useEffect(() => {
    let alive = true;
    if (src) void pageCanvas(src).then((c) => alive && setCanvas(c));
    return () => {
      alive = false;
    };
  }, [src]);
  const key = rects.map((r) => r.map((v) => v.toFixed(1)).join(",")).join("|");
  return useMemo(
    () => rects.map((rect) => (canvas ? sample(canvas, rect, pageWidth) : "#ffffff")),
    // rects are compared by value through ``key``
    [canvas, pageWidth, key],
  );
}
