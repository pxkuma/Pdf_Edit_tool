export type Rect = [number, number, number, number];
export type Point = [number, number];

export interface PageInfo {
  index: number;
  width: number;
  height: number;
  rotation: number;
  label: string;
  token: string;
}

export interface HistoryEntry {
  label: string;
  ts: number;
}

export interface DocInfo {
  id: string;
  filename: string;
  title: string;
  pages: PageInfo[];
  version: string;
  canUndo: boolean;
  canRedo: boolean;
  cursor: number;
  history: HistoryEntry[];
  wasEncrypted: boolean;
  hasForms: boolean;
}

export interface Span {
  id: string;
  text: string;
  bbox: Rect;
  origin: Point;
  dir: Point;
  size: number;
  font: string;
  color: string;
  opacity: number;
  bold: boolean;
  italic: boolean;
  serif: boolean;
  mono: boolean;
  face: string | null;
  /** The PDF's own font family is installed (not just a look-alike). */
  installed?: boolean;
  /** Exact style recovered from the content stream (see backend textstate.py). */
  exact: boolean;
  hscale: number;
  charSpacing: number | null;
  wordSpacing: number;
  rise: number;
  render: string;
  renderMode: number;
  colorSpace: string;
  skew: number;
  /** Invisible text added by OCR on a scanned page. */
  ocr: boolean;
}

export interface TextLine {
  id: string;
  bbox: Rect;
  dir: Point;
  spans: Span[];
}

export interface TextBlock {
  id: string;
  bbox: Rect;
  lines: TextLine[];
}

export interface Word {
  bbox: Rect;
  text: string;
  block: number;
  line: number;
  word: number;
}

export interface Annotation {
  xref: number;
  type: string;
  rect: Rect;
  color: string | null;
  fill: string | null;
  opacity: number;
  width: number;
  contents: string;
  author: string;
  modified: string;
}

export interface PageImage {
  xref: number;
  bbox: Rect;
  width: number;
  height: number;
  editable: boolean;
  uses: number;
}

export interface FormField {
  xref: number;
  page: number;
  name: string;
  label: string;
  type: "text" | "checkbox" | "radio" | "combobox" | "listbox" | "signature" | "button" | "unknown";
  value: string | boolean;
  options: string[];
  onState: string | null;
  rect: Rect;
  readOnly: boolean;
  required: boolean;
  multiline: boolean;
  maxLength: number;
}

export interface PageModel {
  token: string;
  text: { blocks: TextBlock[]; words: Word[] };
  annotations: Annotation[];
  images: PageImage[];
  drawings?: Rect[]; // clusters of vector graphics (rules, boxes, table grids)
  fields: FormField[];
  scan: { scanned: boolean; hasOcr: boolean };
}

export interface FontFaceInfo {
  id: string;
  style: string;
  bold: boolean;
  italic: boolean;
}

export interface FontFamily {
  family: string;
  serif: boolean;
  mono: boolean;
  source: "system" | "user";
  faces: FontFaceInfo[];
}

export interface DocFont {
  xref: number;
  name: string;
  type: string;
  embedded: boolean;
  subset: boolean;
  glyphs: number;
  chars: string;
  installed?: boolean;
}

/** Whether the font a PDF uses can be had: installed, free download, commercial... */
export interface FontLookup {
  name: string;
  family: string;
  status: "installed" | "downloadable" | "commercial" | "unknown" | "offline";
  substitute: string | null;
}

export interface EditReport {
  fonts_used: string[];
  missing_chars: string[];
  exact_font: boolean;
  pushed?: number;
  push_skipped?: string[];
}

export interface MutationResponse<T = unknown> {
  document: DocInfo;
  result: T;
}

export interface SearchHit {
  page: number;
  rect: Rect;
}

export interface TocItem {
  level: number;
  title: string;
  page: number;
}

export interface Metadata {
  title: string;
  author: string;
  subject: string;
  keywords: string;
  creator: string;
  producer: string;
}

export interface TextStyle {
  font: string;
  size: number | null;
  color: string | null;
  bold: boolean | null;
  italic: boolean | null;
  underline: boolean;
  strike: boolean;
  opacity: number | null;
  char_spacing: number | null;
  hscale: number | null;
}

export interface AnnotStyle {
  color: string | null;
  fill: string | null;
  opacity: number;
  width: number;
  dashed: boolean;
  contents: string;
  author: string;
}

export interface OcrCapabilities {
  available: boolean;
  languages: string[];
  default: string | null;
}

export interface Job<T = unknown> {
  id: string;
  docId: string;
  kind: string;
  total: number;
  done: number;
  status: "running" | "done" | "error";
  message: string;
  error: string;
  result: T | null;
  document: DocInfo | null;
}
