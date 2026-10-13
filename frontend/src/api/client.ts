import type {
  AnnotStyle,
  DocFont,
  FontLookup,
  DocInfo,
  EditReport,
  FontFamily,
  FormField,
  Job,
  Metadata,
  OcrCapabilities,
  MutationResponse,
  PageModel,
  Point,
  Rect,
  SearchHit,
  TextStyle,
  TocItem,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string = "error",
  ) {
    super(message);
  }
}

interface Envelope<T> {
  ok: boolean;
  data?: T;
  error?: string;
  code?: string;
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as Envelope<unknown>;
    return new ApiError(body.error || response.statusText, response.status, body.code);
  } catch {
    return new ApiError(`Request failed (${response.status})`, response.status);
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError("Cannot reach the PDF Studio server. Is it running?", 0, "network");
  }
  if (!response.ok) throw await parseError(response);
  const payload = (await response.json()) as Envelope<T>;
  if (!payload.ok) throw new ApiError(payload.error || "Request failed", response.status, payload.code);
  return payload.data as T;
}

async function download(method: string, url: string, body?: unknown): Promise<{ blob: Blob; filename: string }> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const response = await fetch(url, init);
  if (!response.ok) throw await parseError(response);
  const disposition = response.headers.get("Content-Disposition") || "";
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const plain = /filename="([^"]+)"/i.exec(disposition);
  const filename = star ? decodeURIComponent(star[1]) : plain ? plain[1] : "download";
  return { blob: await response.blob(), filename };
}

const doc = (id: string) => `/api/documents/${id}`;
type Mut<T = unknown> = Promise<MutationResponse<T>>;

export const api = {
  upload(file: File, password?: string): Promise<DocInfo> {
    const form = new FormData();
    form.append("file", file);
    if (password) form.append("password", password);
    return request("POST", "/api/documents", form);
  },
  info: (id: string) => request<DocInfo>("GET", doc(id)),
  close: (id: string) => request<null>("DELETE", doc(id)),
  undo: (id: string) => request<DocInfo>("POST", `${doc(id)}/undo`),
  redo: (id: string) => request<DocInfo>("POST", `${doc(id)}/redo`),
  jump: (id: string, index: number) => request<DocInfo>("POST", `${doc(id)}/history/${index}`),
  revert: (id: string): Mut => request("POST", `${doc(id)}/revert`),

  renderUrl: (id: string, page: number, scale: number, token: string) =>
    `${doc(id)}/pages/${page}/render?scale=${scale}&t=${token}`,
  pageModel: (id: string, page: number) => request<PageModel>("GET", `${doc(id)}/pages/${page}/model`),
  fonts: () => request<{ families: FontFamily[]; default: string | null }>("GET", "/api/fonts"),
  fontFileUrl: (faceId: string) => `/api/fonts/${faceId}/file`,
  uploadFont(file: File): Promise<{ id: string; family: string; style: string }> {
    const form = new FormData();
    form.append("file", file);
    return request("POST", "/api/fonts", form);
  },
  docFonts: (id: string) => request<DocFont[]>("GET", `${doc(id)}/fonts`),
  fontLookup: (name: string) => request<FontLookup>("GET", `/api/fonts/lookup?name=${encodeURIComponent(name)}`),
  downloadFont: (name: string) =>
    request<{ family: string; face: string; faces: { id: string; style: string }[] }>("POST", "/api/fonts/download", { name }),
  search: (id: string, q: string) => request<SearchHit[]>("GET", `${doc(id)}/search?q=${encodeURIComponent(q)}`),

  editSpan: (
    id: string,
    body: {
      page: number;
      bbox: Rect;
      origin: Point;
      original_text: string;
      text: string;
      style: Partial<TextStyle>;
      dx?: number;
      dy?: number;
      fit_width?: boolean;
      reflow?: boolean;
      ocr_mode?: "replace" | "hidden";
    },
  ): Mut<EditReport> => request("POST", `${doc(id)}/text/span`, body),
  editBlock: (
    id: string,
    body: {
      page: number;
      bbox: Rect;
      text: string;
      style: Partial<TextStyle>;
      align: string;
      line_height?: number | null;
      width?: number | null;
      max_width?: number | null;
      dx?: number;
      dy?: number;
    },
  ): Mut<EditReport> => request("POST", `${doc(id)}/text/block`, body),
  addText: (
    id: string,
    body: {
      page: number;
      x: number;
      y: number;
      text: string;
      style: Partial<TextStyle>;
      width?: number | null;
      max_width?: number | null;
      align: string;
      line_height: number;
      rotation: number;
    },
  ): Mut<EditReport> => request("POST", `${doc(id)}/text/add`, body),
  replace: (
    id: string,
    body: { query: string; replacement: string; pages?: string; match_case: boolean; whole_word: boolean },
  ): Mut<{ replaced: number; skipped: number; pages: number[] }> => request("POST", `${doc(id)}/text/replace`, body),

  addAnnotation: (id: string, body: Record<string, unknown>): Mut<number> => request("POST", `${doc(id)}/annotations`, body),
  updateAnnotation: (id: string, page: number, xref: number, style: AnnotStyle, rect?: Rect | null): Mut =>
    request("PATCH", `${doc(id)}/annotations/${page}/${xref}`, { style, rect: rect ?? null }),
  deleteAnnotation: (id: string, page: number, xref: number): Mut =>
    request("DELETE", `${doc(id)}/annotations/${page}/${xref}`),

  addImage(id: string, page: number, rect: Rect, file: Blob, keepProportion = true): Mut {
    const form = new FormData();
    form.append("page", String(page));
    form.append("rect", rect.join(","));
    form.append("keep_proportion", String(keepProportion));
    form.append("file", file, "image.png");
    return request("POST", `${doc(id)}/images`, form);
  },
  moveImage: (id: string, page: number, xref: number, rect: Rect): Mut =>
    request("POST", `${doc(id)}/images/${page}/${xref}/move`, { rect }),
  replaceImage(id: string, page: number, xref: number, file: File): Mut {
    const form = new FormData();
    form.append("file", file);
    return request("POST", `${doc(id)}/images/${page}/${xref}/replace`, form);
  },
  deleteImage: (id: string, page: number, xref: number): Mut => request("DELETE", `${doc(id)}/images/${page}/${xref}`),
  imageUrl: (id: string, xref: number) => `${doc(id)}/images/${xref}`,

  rotatePages: (id: string, pages: number[], angle: number): Mut => request("POST", `${doc(id)}/pages/rotate`, { pages, angle }),
  reorderPages: (id: string, order: number[]): Mut => request("POST", `${doc(id)}/pages/reorder`, { order }),
  deletePages: (id: string, pages: number[]): Mut => request("POST", `${doc(id)}/pages/delete`, { pages }),
  duplicatePages: (id: string, pages: number[]): Mut => request("POST", `${doc(id)}/pages/duplicate`, { pages }),
  insertBlank: (id: string, at: number, size: string, landscape: boolean): Mut =>
    request("POST", `${doc(id)}/pages/insert-blank`, { at, size, landscape }),
  insertFile(id: string, at: number, file: File): Mut {
    const form = new FormData();
    form.append("at", String(at));
    form.append("file", file);
    return request("POST", `${doc(id)}/pages/insert-file`, form);
  },
  cropPages: (id: string, pages: number[], rect: Rect): Mut => request("POST", `${doc(id)}/pages/crop`, { pages, rect }),
  resetCrop: (id: string, pages: number[]): Mut => request("POST", `${doc(id)}/pages/reset-crop`, { pages }),

  redact: (id: string, page: number, rects: Rect[], mode: string, color: string): Mut =>
    request("POST", `${doc(id)}/redact`, { page, rects, mode, color }),
  redactSearch: (id: string, query: string, pages: string, color: string): Mut<{ redacted: number }> =>
    request("POST", `${doc(id)}/redact/search`, { query, pages: pages || null, color }),
  watermark: (id: string, body: Record<string, unknown>): Mut => request("POST", `${doc(id)}/watermark`, body),
  imageWatermark(id: string, file: File, pages: string, scale: number, opacity: number): Mut {
    const form = new FormData();
    form.append("file", file);
    form.append("pages", pages);
    form.append("scale", String(scale));
    form.append("opacity", String(opacity));
    return request("POST", `${doc(id)}/watermark/image`, form);
  },
  headerFooter: (id: string, body: Record<string, unknown>): Mut => request("POST", `${doc(id)}/header-footer`, body),

  metadata: (id: string) => request<Metadata>("GET", `${doc(id)}/metadata`),
  setMetadata: (id: string, body: Partial<Metadata>): Mut => request("PUT", `${doc(id)}/metadata`, body),
  toc: (id: string) => request<TocItem[]>("GET", `${doc(id)}/toc`),
  setToc: (id: string, items: TocItem[]): Mut => request("PUT", `${doc(id)}/toc`, { items }),

  forms: (id: string) => request<FormField[]>("GET", `${doc(id)}/forms`),
  fillForms: (id: string, values: { page: number; xref: number; value: string | boolean }[]): Mut =>
    request("PUT", `${doc(id)}/forms`, { values }),
  addField: (id: string, body: { page: number; kind: string; rect: Rect; name: string }): Mut =>
    request("POST", `${doc(id)}/forms`, body),
  deleteField: (id: string, page: number, xref: number): Mut => request("DELETE", `${doc(id)}/forms/${page}/${xref}`),
  flatten: (id: string, annotations: boolean, forms: boolean): Mut =>
    request("POST", `${doc(id)}/flatten`, { annotations, forms }),

  ocrInfo: () => request<OcrCapabilities>("GET", "/api/ocr"),
  startOcr: (id: string, body: { pages: string | null; language: string; dpi: number; force: boolean }) =>
    request<Job>("POST", `${doc(id)}/ocr`, body),
  job: <T,>(jobId: string) => request<Job<T>>("GET", `/api/jobs/${jobId}`),

  exportPdf: (id: string, options: Record<string, unknown>) => download("POST", `${doc(id)}/export`, options),
  exportImages: (id: string, options: Record<string, unknown>) => download("POST", `${doc(id)}/export/images`, options),
  exportExtract: (id: string, pages: string) => download("POST", `${doc(id)}/export/extract`, { pages }),
  exportSplit: (id: string, every: number) => download("POST", `${doc(id)}/export/split`, { every }),
  exportText: (id: string) => download("GET", `${doc(id)}/export/text`),
  exportOriginal: (id: string) => download("GET", `${doc(id)}/original`),
};
