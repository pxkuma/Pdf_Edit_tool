import type { Rect } from "./types";

export type CompareMode = "text" | "visual" | "both";
export type Sensitivity = "low" | "medium" | "high";

/** What the user chose on the Compare screen (sent to the server as the run request). */
export interface CompareSettings {
  mode: CompareMode;
  dpi: number;
  sensitivity: Sensitivity;
  ignoreCase: boolean;
}

export interface CompareSessionPage {
  index: number;
  width: number;
  height: number;
}

/** The second file of a comparison. It lives temporarily on the server and is not a document. */
export interface CompareSession {
  id: string;
  docId: string;
  filename: string;
  created: number;
  pageCount: number;
  pages: CompareSessionPage[];
  hasReport: boolean;
}

export type ChangeKind = "text" | "visual" | "page";
export type ChangeType = "insert" | "delete" | "replace" | "region" | "resize";
export type PairStatus = "matched" | "changed" | "inserted" | "removed";

export interface CompareChange {
  id: string;
  kind: ChangeKind;
  type: ChangeType;
  pair: number;
  pageA: number | null;
  pageB: number | null;
  oldText: string;
  newText: string;
  before: string;
  after: string;
  /** Where the old words or the changed region are on the first document (page points, top-left origin). */
  rectsA: Rect[];
  rectsB: Rect[];
  /** An insertion's place on the first document / a deletion's place on the second. */
  anchorA: Rect | null;
  anchorB: Rect | null;
  pixels?: number;
}

export interface ComparePair {
  index: number;
  pageA: number | null;
  pageB: number | null;
  status: PairStatus;
  similarity: number;
  sizeA: [number, number] | null;
  sizeB: [number, number] | null;
  sizeChanged: boolean;
  text: { wordsA: number; wordsB: number; inserted: number; deleted: number } | null;
  visual: { dpi: number; regions: number; explainedByText: number } | null;
  changes: CompareChange[];
}

export interface CompareTotals {
  pairs: number;
  matched: number;
  changed: number;
  inserted: number;
  removed: number;
  changes: number;
  textChanges: number;
  visualChanges: number;
  pageChanges: number;
  pagesWithChanges: number;
  wordsInserted: number;
  wordsDeleted: number;
}

export interface CompareReport {
  options: CompareSettings;
  pairs: ComparePair[];
  totals: CompareTotals;
  /** Version of the open document that was compared; a different one means the report is out of date. */
  baseVersion: string;
  base: { filename: string; pages: number };
  other: { filename: string; pages: number };
}
