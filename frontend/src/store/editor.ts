import { create } from "zustand";
import { ApiError } from "../api/client";
import type { DocInfo, MutationResponse, Rect, SearchHit, Span } from "../api/types";

export type Tool =
  | "select"
  | "pan"
  | "editText"
  | "addText"
  | "highlight"
  | "underline"
  | "strikeout"
  | "squiggly"
  | "ink"
  | "rect"
  | "ellipse"
  | "line"
  | "arrow"
  | "note"
  | "textbox"
  | "image"
  | "whiteout"
  | "redact"
  | "eraseText"
  | "crop"
  | "fieldText"
  | "fieldCheckbox";

export type Selection =
  | { kind: "annotation"; page: number; xref: number }
  | { kind: "image"; page: number; xref: number }
  | { kind: "field"; page: number; xref: number }
  | null;

export type SidebarPanel = "thumbnails" | "outline" | "search" | "forms" | "history" | "fonts" | null;

export type DialogName =
  | "export"
  | "watermark"
  | "headerFooter"
  | "metadata"
  | "signature"
  | "stamp"
  | "insertPages"
  | "shortcuts"
  | "protect"
  | "redactSearch"
  | "ocr"
  | null;

export interface NewTextStyle {
  faceId: string | null;
  size: number;
  color: string;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strike: boolean;
  opacity: number;
  align: "left" | "center" | "right" | "justify";
  lineHeight: number;
}

export interface DrawStyle {
  color: string;
  fill: string | null;
  width: number;
  opacity: number;
  dashed: boolean;
}

export interface SpanDraft {
  font: string; // "original" | "face:<id>" | "doc:<xref>"
  size: number;
  color: string;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strike: boolean;
  opacity: number;
  charSpacing: number | null;
  hscale: number;
  fitWidth: boolean;
  reflow: boolean;
  ocrMode: "replace" | "hidden";
}

/** Geometry of a text box being edited, relative to its original block (points). */
export interface BoxDraft {
  dx: number;
  dy: number;
  width: number | null; // null = auto width (grow into free space, then wrap)
}

export const AUTO_BOX: BoxDraft = { dx: 0, dy: 0, width: null };

/** How content below a growing text box moves (see lib/push.ts). */
export interface PushDraft {
  enabled: boolean;
  scope: "column" | "page";
  follow: boolean; // also pull content up when the box gets shorter
  extra: number; // extra spacing (pt) on top of the growth
  overrides: Record<string, boolean>; // per item: true = move, false = keep
}

export const DEFAULT_PUSH: PushDraft = { enabled: true, scope: "column", follow: false, extra: 0, overrides: {} };

/** Where the text box currently is (page points), for the X/Y/W fields. */
export interface BoxInfo {
  x: number;
  y: number;
  width: number;
  auto: boolean;
}

/** What the live preview currently moves (shown in Properties). */
export interface PushInfo {
  count: number;
  dy: number;
  offPage: number;
  conflicts: number; // kept items that moved content would overlap
}

export interface ActiveEdit {
  mode: "span" | "block";
  page: number;
  span: Span;
  blockId?: string;
  boxSpanIds?: string[]; // spans replaced by the text box
  boxSpans?: Span[];
  boxLines?: Rect[]; // the box's line rectangles (for exact moves and deletion)
  typing?: boolean; // false: selected (move/resize), true: editing its text
  uniform?: boolean; // one style: can be retyped as a whole without losing formatting
  pressedAt?: number; // when it was selected (a second press soon after = double-click)
  blockBbox?: Rect;
  blockText?: string;
  lineStep?: number; // original baseline distance (pt) at the span's size
  lineHeight?: number | null; // multiple of the font size; null = original spacing
  box?: BoxDraft;
  lineCount?: number; // lines the box had originally
  push?: PushDraft;
  pushInfo?: PushInfo;
  boxInfo?: BoxInfo;
  draft: SpanDraft;
  align: "left" | "center" | "right" | "justify";
}

export interface Placement {
  blob: Blob;
  url: string;
  width: number;
  height: number;
  label: string;
}

export interface Toast {
  id: number;
  kind: "info" | "success" | "error" | "warning";
  message: string;
}

interface EditorState {
  doc: DocInfo | null;
  zoom: number;
  fit: "width" | "page" | null;
  tool: Tool;
  selection: Selection;
  selectedPages: number[];
  currentPage: number;
  busy: number;
  sidebar: SidebarPanel;
  propertiesOpen: boolean;
  dialog: DialogName;
  newText: NewTextStyle;
  markup: { color: string; opacity: number };
  ink: DrawStyle;
  shape: DrawStyle;
  redactColor: string;
  activeEdit: ActiveEdit | null;
  placement: Placement | null;
  searchHits: SearchHit[];
  activeHit: number;
  toasts: Toast[];
  scrollRequest: { page: number; y?: number; nonce: number } | null;
  textPreset: string | null;
}

interface EditorActions {
  setDoc: (doc: DocInfo | null) => void;
  setZoom: (zoom: number, fit?: "width" | "page" | null) => void;
  setTool: (tool: Tool) => void;
  select: (selection: Selection) => void;
  setSelectedPages: (pages: number[]) => void;
  setCurrentPage: (page: number) => void;
  setSidebar: (panel: SidebarPanel) => void;
  toggleProperties: () => void;
  openDialog: (dialog: DialogName) => void;
  patchNewText: (patch: Partial<NewTextStyle>) => void;
  patchMarkup: (patch: Partial<{ color: string; opacity: number }>) => void;
  patchInk: (patch: Partial<DrawStyle>) => void;
  patchShape: (patch: Partial<DrawStyle>) => void;
  setRedactColor: (color: string) => void;
  setActiveEdit: (edit: ActiveEdit | null) => void;
  patchDraft: (patch: Partial<SpanDraft>) => void;
  patchEdit: (patch: Partial<ActiveEdit>) => void;
  setPlacement: (placement: Placement | null) => void;
  setSearch: (hits: SearchHit[], active?: number) => void;
  setActiveHit: (index: number) => void;
  toast: (message: string, kind?: Toast["kind"]) => void;
  dismissToast: (id: number) => void;
  scrollTo: (page: number, y?: number) => void;
  setTextPreset: (text: string | null) => void;
  run: <T>(fn: () => Promise<MutationResponse<T>>, success?: string) => Promise<T | undefined>;
  track: <T>(fn: () => Promise<T>) => Promise<T | undefined>;
}

const STYLE_KEY = "pdfstudio.styles";

function readStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...(JSON.parse(raw) as T) } : fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: preferences simply aren't remembered */
  }
}

const defaultStyles = {
  newText: {
    faceId: null,
    size: 12,
    color: "#111111",
    bold: false,
    italic: false,
    underline: false,
    strike: false,
    opacity: 1,
    align: "left",
    lineHeight: 1.2,
  } as NewTextStyle,
  markup: { color: "#ffd400", opacity: 0.6 },
  ink: { color: "#e11d48", fill: null, width: 2, opacity: 1, dashed: false } as DrawStyle,
  shape: { color: "#2563eb", fill: null, width: 2, opacity: 1, dashed: false } as DrawStyle,
  redactColor: "#000000",
};

const savedStyles = readStorage(STYLE_KEY, defaultStyles);
let toastId = 0;

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

export const useEditor = create<EditorState & EditorActions>((set, get) => {
  const persistStyles = () => {
    const { newText, markup, ink, shape, redactColor } = get();
    writeStorage(STYLE_KEY, { newText, markup, ink, shape, redactColor });
  };

  return {
    doc: null,
    zoom: 1,
    fit: "width",
    tool: "select",
    selection: null,
    selectedPages: [],
    currentPage: 0,
    busy: 0,
    sidebar: "thumbnails",
    propertiesOpen: true,
    dialog: null,
    newText: savedStyles.newText,
    markup: savedStyles.markup,
    ink: savedStyles.ink,
    shape: savedStyles.shape,
    redactColor: savedStyles.redactColor,
    activeEdit: null,
    placement: null,
    searchHits: [],
    activeHit: -1,
    toasts: [],
    scrollRequest: null,
    textPreset: null,

    setDoc: (doc) =>
      set((state) => {
        const count = doc?.pages.length ?? 0;
        const sameDoc = state.doc?.id === doc?.id;
        return {
          doc,
          selection: sameDoc ? state.selection : null,
          selectedPages: state.selectedPages.filter((p) => p < count),
          currentPage: Math.min(state.currentPage, Math.max(0, count - 1)),
          activeEdit: sameDoc ? state.activeEdit : null,
        };
      }),
    setZoom: (zoom, fit = null) => set({ zoom: Math.min(6, Math.max(0.1, zoom)), fit }),
    setTool: (tool) =>
      set((state) => ({
        tool,
        selection: null,
        activeEdit: null,
        textPreset: tool === "addText" ? state.textPreset : null,
        placement: tool === "image" ? state.placement : null,
      })),
    select: (selection) => set({ selection }),
    setSelectedPages: (pages) => set({ selectedPages: pages }),
    setCurrentPage: (page) => set({ currentPage: page }),
    setSidebar: (panel) => set((state) => ({ sidebar: state.sidebar === panel ? null : panel })),
    toggleProperties: () => set((state) => ({ propertiesOpen: !state.propertiesOpen })),
    openDialog: (dialog) => set({ dialog }),
    patchNewText: (patch) => {
      set((state) => ({ newText: { ...state.newText, ...patch } }));
      persistStyles();
    },
    patchMarkup: (patch) => {
      set((state) => ({ markup: { ...state.markup, ...patch } }));
      persistStyles();
    },
    patchInk: (patch) => {
      set((state) => ({ ink: { ...state.ink, ...patch } }));
      persistStyles();
    },
    patchShape: (patch) => {
      set((state) => ({ shape: { ...state.shape, ...patch } }));
      persistStyles();
    },
    setRedactColor: (color) => {
      set({ redactColor: color });
      persistStyles();
    },
    setActiveEdit: (edit) => set({ activeEdit: edit }),
    patchDraft: (patch) =>
      set((state) =>
        state.activeEdit ? { activeEdit: { ...state.activeEdit, draft: { ...state.activeEdit.draft, ...patch } } } : {},
      ),
    patchEdit: (patch) => set((state) => (state.activeEdit ? { activeEdit: { ...state.activeEdit, ...patch } } : {})),
    setPlacement: (placement) =>
      set((state) => {
        if (state.placement && state.placement.url !== placement?.url) URL.revokeObjectURL(state.placement.url);
        return { placement };
      }),
    setSearch: (hits, active = hits.length ? 0 : -1) => set({ searchHits: hits, activeHit: active }),
    setActiveHit: (index) => set({ activeHit: index }),
    toast: (message, kind = "info") => {
      const id = ++toastId;
      set((state) => ({ toasts: [...state.toasts.slice(-4), { id, kind, message }] }));
      window.setTimeout(() => get().dismissToast(id), kind === "error" ? 7000 : 3500);
    },
    dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
    scrollTo: (page, y) => set({ scrollRequest: { page, y, nonce: Date.now() } }),
    setTextPreset: (text) => set({ textPreset: text }),

    run: async (fn, success) => {
      set((state) => ({ busy: state.busy + 1 }));
      try {
        const response = await fn();
        get().setDoc(response.document);
        if (success) get().toast(success, "success");
        return response.result;
      } catch (error) {
        get().toast(errorMessage(error), "error");
        return undefined;
      } finally {
        set((state) => ({ busy: Math.max(0, state.busy - 1) }));
      }
    },
    track: async (fn) => {
      set((state) => ({ busy: state.busy + 1 }));
      try {
        return await fn();
      } catch (error) {
        get().toast(errorMessage(error), "error");
        return undefined;
      } finally {
        set((state) => ({ busy: Math.max(0, state.busy - 1) }));
      }
    },
  };
});
