export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function pickFile(accept: string): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.addEventListener("cancel", () => resolve(null));
    input.click();
  });
}

export function imageSize(blob: Blob): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
      URL.revokeObjectURL(url);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("This image could not be read."));
    };
    img.src = url;
  });
}

export function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not create image"))), "image/png"),
  );
}

/** Crop transparent margins of a canvas (used for signatures and stamps). */
export function trimCanvas(source: HTMLCanvasElement, padding = 6): HTMLCanvasElement {
  const ctx = source.getContext("2d");
  if (!ctx) return source;
  const { width, height } = source;
  const data = ctx.getImageData(0, 0, width, height).data;
  let x0 = width,
    y0 = height,
    x1 = -1,
    y1 = -1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (data[(y * width + x) * 4 + 3] > 8) {
        if (x < x0) x0 = x;
        if (y < y0) y0 = y;
        if (x > x1) x1 = x;
        if (y > y1) y1 = y;
      }
    }
  }
  if (x1 < 0) return source;
  x0 = Math.max(0, x0 - padding);
  y0 = Math.max(0, y0 - padding);
  x1 = Math.min(width - 1, x1 + padding);
  y1 = Math.min(height - 1, y1 + padding);
  const out = document.createElement("canvas");
  out.width = x1 - x0 + 1;
  out.height = y1 - y0 + 1;
  out.getContext("2d")?.drawImage(source, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
  return out;
}

const RECENT_KEY = "pdfstudio.recent";

export interface RecentDoc {
  id: string;
  filename: string;
  pages: number;
  ts: number;
}

export function recentDocs(): RecentDoc[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const parsed = raw ? (JSON.parse(raw) as RecentDoc[]) : [];
    return Array.isArray(parsed) ? parsed.filter((d) => typeof d.id === "string") : [];
  } catch {
    return [];
  }
}

export function rememberDoc(doc: RecentDoc): void {
  try {
    const list = [doc, ...recentDocs().filter((d) => d.id !== doc.id)].slice(0, 12);
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch {
    /* ignore */
  }
}

export function forgetDoc(id: string): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(recentDocs().filter((d) => d.id !== id)));
  } catch {
    /* ignore */
  }
}
