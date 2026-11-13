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
  /** Number of digital (certificate) signatures in the document. */
  signatures: number;
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
  /** Underline / strikethrough lines drawn for this text (detected on the page). */
  underline?: boolean;
  strike?: boolean;
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

/** Review status of a comment, as Acrobat records it. */
export type CommentStatus = "none" | "accepted" | "rejected" | "cancelled" | "completed";

/** A reply (or a comment: see ``PdfComment``). Dates are UTC ISO strings, empty when the file has none. */
export interface CommentReply {
  id: string;
  page: number;
  xref: number;
  name: string;
  type: string; // PDF annotation type: Text, Highlight, Underline, StrikeOut, Squiggly, FreeText, Ink ...
  author: string;
  subject: string;
  contents: string;
  created: string;
  modified: string;
  color: string | null;
  rect: Rect;
  quote: string; // the text a markup comment covers
  status: CommentStatus;
  statusBy: string;
  statusDate: string;
  checked: boolean;
  parent: number | null;
  depth: number; // 1 = answers the comment, 2 = answers a reply ...
}

export interface PdfComment extends Omit<CommentReply, "depth"> {
  replies: CommentReply[];
}

export interface CommentList {
  comments: PdfComment[];
  authors: string[];
  count: number; // comments and replies
}

export interface XfdfImportResult {
  added: number;
  updated: number;
  unchanged: number;
  skipped: number;
  warnings: string[];
  pages: number[];
}

export interface PageImage {
  xref: number;
  bbox: Rect; // footprint on the page (rotated bounding box)
  rect: Rect; // un-rotated placement rectangle
  angle: number; // visual clockwise rotation in degrees
  opacity: number;
  width: number;
  height: number;
  editable: boolean;
  uses: number;
}

export interface ImagePlacement {
  rect: Rect;
  angle?: number;
  opacity?: number;
  overlay?: boolean;
}

export interface ImageAdjust {
  brightness?: number;
  contrast?: number;
  saturation?: number;
  grayscale?: boolean;
  flip_h?: boolean;
  flip_v?: boolean;
  crop?: Rect;
}

export type FormFieldKind = "text" | "checkbox" | "radio" | "combobox" | "listbox" | "signature" | "button" | "unknown";
export type FieldValue = string | boolean | string[];
export type FieldAlign = "left" | "center" | "right";
export type FieldBorderStyle = "solid" | "dashed" | "beveled" | "inset" | "underline";
export type ButtonAction = "none" | "reset" | "print" | "url" | "submit" | "other";

export interface FieldChoice {
  value: string; // export value
  label: string; // what the list shows
}

export interface FieldFormat {
  kind: "none" | "number" | "date";
  decimals: number;
  pattern: string;
}

export interface FormField {
  xref: number;
  page: number;
  name: string;
  label: string;
  type: FormFieldKind;
  value: FieldValue;
  options: string[];
  onState: string | null;
  rect: Rect;
  readOnly: boolean;
  required: boolean;
  multiline: boolean;
  maxLength: number;
  tabIndex: number;
  tooltip: string;
  defaultValue: string | string[];
  font: string;
  fontSize: number; // 0 = auto
  textColor: string;
  fillColor: string | null;
  borderColor: string | null;
  borderWidth: number;
  borderStyle: FieldBorderStyle;
  align: FieldAlign;
  comb: boolean;
  format: FieldFormat;
  choices: FieldChoice[];
  editable: boolean;
  multiSelect: boolean;
  caption: string;
  action: ButtonAction;
  url: string;
  group: number; // radio: number of buttons in the group
  signed: boolean;
}

/** A partial property edit (snake_case, as the server expects). Fields left out keep their value. */
export interface FieldPatch {
  name?: string;
  tooltip?: string;
  required?: boolean;
  read_only?: boolean;
  default_value?: string | boolean | string[];
  font?: "Helvetica" | "Times" | "Courier";
  font_size?: number;
  text_color?: string;
  fill_color?: string; // "#rrggbb" or "none"
  border_color?: string; // "#rrggbb" or "none"
  border_width?: number;
  border_style?: FieldBorderStyle;
  align?: FieldAlign;
  multiline?: boolean;
  max_length?: number;
  comb?: boolean;
  format?: FieldFormat;
  options?: FieldChoice[];
  editable?: boolean;
  multi_select?: boolean;
  export_value?: string;
  caption?: string;
  action?: Exclude<ButtonAction, "other">;
  url?: string;
  rect?: Rect;
}

export interface NewFieldRequest {
  page: number;
  kind: Exclude<FormFieldKind, "unknown">;
  rect: Rect;
  name?: string;
  props?: FieldPatch;
}

export interface CreatedField {
  xref: number;
  page: number;
  name: string;
  kind: string;
}

export interface TabOrder {
  page: number;
  mode: "manual" | "row" | "column" | "structure";
  fields: { xref: number; name: string; rect: Rect }[];
}

/** A field the server recognised on the page; nothing is added until the user accepts it. */
export interface FieldProposal {
  id: string;
  page: number;
  kind: Exclude<FormFieldKind, "unknown">;
  rect: Rect;
  name: string;
  label: string;
  confidence: number;
  reason: string;
  multiline: boolean;
  format: { kind: "date"; pattern: string } | null;
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

/** What stamping text (watermark, header/footer) reports: characters no installed font could draw. */
export interface StampResult {
  missing_chars: string[];
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

/** What a redaction also removed (comments, form fields and links under the area). */
export interface RedactResult {
  annotations: number;
  fields: number;
  links: number;
  sanitized: boolean;
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

export type SignatureVerdict = "valid" | "unknown" | "modified" | "invalid";

export interface SignerInfo {
  name: string;
  email: string;
  organization: string;
  issuer: string;
  serial: string;
  valid_from: string;
  valid_to: string;
  self_signed: boolean;
}

/** Validation of one digital signature (see backend sigvalidate.py). */
export interface SignatureReport {
  field: string;
  page: number | null;
  rect: Rect | null;
  revision: number;
  signer: SignerInfo | null;
  signing_time: string | null;
  timestamp: string | null;
  timestamp_valid: boolean | null;
  reason: string;
  location: string;
  certified: boolean;
  intact: boolean;
  valid: boolean;
  trusted: boolean;
  trust_note: string;
  covers_whole_file: boolean;
  modification: "none" | "validation_data" | "form_filling" | "annotations" | "other" | "unknown";
  changes_allowed: boolean;
  status: SignatureVerdict;
  summary: string;
  error: string | null;
}

export interface SignatureValidation {
  version: string;
  summary: { count: number; overall: SignatureVerdict | "none"; valid: number; unknown: number; modified: number; invalid: number };
  signatures: SignatureReport[];
}

export interface SignRequest {
  certificate: File;
  password: string;
  placement: { page: number; rect: Rect } | null;
  field?: string | null; // sign into this existing empty signature field instead of placing a new one
  reason: string;
  location: string;
  contact: string;
  timestampUrl: string;
  showDetails: boolean;
  image: Blob | null;
  utcOffset: number;
}

export interface SignResult {
  field: string;
  signer: string;
  visible: boolean;
  timestamped: boolean;
}
