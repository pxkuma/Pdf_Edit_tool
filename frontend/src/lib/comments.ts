import type { CommentReply, CommentStatus, PdfComment, Point, XfdfImportResult } from "../api/types";

export const STATUSES: CommentStatus[] = ["none", "accepted", "rejected", "cancelled", "completed"];

export const STATUS_LABEL: Record<CommentStatus, string> = {
  none: "No status",
  accepted: "Accepted",
  rejected: "Rejected",
  cancelled: "Cancelled",
  completed: "Completed",
};

const TYPE_LABEL: Record<string, string> = {
  Text: "Note",
  Highlight: "Highlight",
  Underline: "Underline",
  StrikeOut: "Strikeout",
  Squiggly: "Squiggly",
  FreeText: "Text box",
  Ink: "Drawing",
  Line: "Line",
  Square: "Rectangle",
  Circle: "Ellipse",
  Polygon: "Polygon",
  PolyLine: "Polyline",
  Caret: "Insert mark",
  Stamp: "Stamp",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export type CommentSort = "page" | "date" | "author";

export const SORT_LABEL: Record<CommentSort, string> = { page: "Page", date: "Date", author: "Author" };

export interface CommentFilter {
  author: string; // "" = everyone
  type: string; // "" = every type; otherwise a PDF annotation type
  status: CommentStatus | "all";
  query: string;
}

export const NO_FILTER: CommentFilter = { author: "", type: "", status: "all", query: "" };

export function typeLabel(type: string): string {
  return TYPE_LABEL[type] ?? type;
}

export function authorLabel(author: string): string {
  return author.trim() || "Unknown";
}

export function isFiltering(filter: CommentFilter): boolean {
  return Boolean(filter.author || filter.type || filter.status !== "all" || filter.query.trim());
}

/** Everyone who wrote the comment or one of its replies. */
export function threadAuthors(comment: PdfComment): string[] {
  return [...new Set([comment.author, ...comment.replies.map((r) => r.author)].filter(Boolean))];
}

/** When the thread last changed (ISO strings of one format sort as text). */
export function lastActivity(comment: PdfComment): string {
  return [comment.modified, comment.created, ...comment.replies.flatMap((r) => [r.modified, r.created])].reduce(
    (latest, value) => (value > latest ? value : latest),
    "",
  );
}

function searchable(item: PdfComment | CommentReply): string {
  return `${item.contents}\n${item.subject}\n${item.author}\n${item.quote}`.toLowerCase();
}

/** A thread matches when the comment fits every set criterion; author and text also look at the replies. */
export function matchesFilter(comment: PdfComment, filter: CommentFilter): boolean {
  if (filter.author && !threadAuthors(comment).includes(filter.author)) return false;
  if (filter.type && comment.type !== filter.type) return false;
  if (filter.status !== "all" && comment.status !== filter.status) return false;
  const query = filter.query.trim().toLowerCase();
  return !query || [comment, ...comment.replies].some((item) => searchable(item).includes(query));
}

export function filterComments(comments: PdfComment[], filter: CommentFilter): PdfComment[] {
  return isFiltering(filter) ? comments.filter((c) => matchesFilter(c, filter)) : comments;
}

function inPageOrder(a: PdfComment, b: PdfComment): number {
  return a.page - b.page || a.rect[1] - b.rect[1] || a.rect[0] - b.rect[0] || a.xref - b.xref;
}

/** A sorted copy: by page (top to bottom), newest activity first, or by author name. */
export function sortComments(comments: PdfComment[], sort: CommentSort): PdfComment[] {
  const copy = [...comments];
  if (sort === "date") {
    return copy.sort((a, b) => lastActivity(b).localeCompare(lastActivity(a)) || inPageOrder(a, b));
  }
  if (sort === "author") {
    const name = (c: PdfComment) => c.author.trim().toLowerCase();
    return copy.sort((a, b) => {
      if (!name(a) !== !name(b)) return name(a) ? -1 : 1; // unsigned comments last
      return name(a).localeCompare(name(b)) || inPageOrder(a, b);
    });
  }
  return copy.sort(inPageOrder);
}

export interface CommentGroup {
  key: string;
  title: string;
  comments: PdfComment[];
}

function dayKey(moment: Date): string {
  return `${moment.getFullYear()}-${moment.getMonth() + 1}-${moment.getDate()}`;
}

function dayTitle(moment: Date, now: Date): string {
  if (dayKey(moment) === dayKey(now)) return "Today";
  if (dayKey(moment) === dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))) return "Yesterday";
  return `${MONTHS[moment.getMonth()]} ${moment.getDate()}, ${moment.getFullYear()}`;
}

function groupOf(comment: PdfComment, sort: CommentSort, now: Date): { key: string; title: string } {
  if (sort === "page") return { key: `page-${comment.page}`, title: `Page ${comment.page + 1}` };
  if (sort === "author") return { key: `author-${comment.author.trim().toLowerCase()}`, title: authorLabel(comment.author) };
  const moment = new Date(lastActivity(comment));
  return Number.isNaN(moment.getTime()) ? { key: "no-date", title: "No date" } : { key: dayKey(moment), title: dayTitle(moment, now) };
}

/** Headings for a list that is already sorted: pages, authors or days, in the order they first appear. */
export function groupComments(comments: PdfComment[], sort: CommentSort, now: Date = new Date()): CommentGroup[] {
  const groups: CommentGroup[] = [];
  const byKey = new Map<string, CommentGroup>();
  for (const comment of comments) {
    const { key, title } = groupOf(comment, sort, now);
    let group = byKey.get(key);
    if (!group) {
      group = { key, title, comments: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.comments.push(comment);
  }
  return groups;
}

/** The annotation types that occur, in the order of the type menu. */
export function presentTypes(comments: PdfComment[]): string[] {
  const order = Object.keys(TYPE_LABEL);
  const rank = (type: string) => (order.includes(type) ? order.indexOf(type) : order.length);
  return [...new Set(comments.map((c) => c.type))].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  const letters = words.length === 1 ? [...words[0]].slice(0, 2) : [[...words[0]][0], [...words[words.length - 1]][0]];
  return letters.join("").toUpperCase();
}

/** "just now", "5 min ago", "3 h ago", "2 d ago", then the date. Empty when the date is unknown. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const moment = new Date(iso);
  if (!iso || Number.isNaN(moment.getTime())) return "";
  const seconds = Math.max(0, (now.getTime() - moment.getTime()) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  if (seconds < 7 * 86400) return `${Math.round(seconds / 86400)} d ago`;
  return `${MONTHS[moment.getMonth()]} ${moment.getDate()}, ${moment.getFullYear()}`;
}

const NOTE_ORIGIN = 36;
const NOTE_STEP = 24;

/** Where a quick-added note goes on a page: the first free slot of a diagonal run from the top-left corner. */
export function nextNotePosition(comments: PdfComment[], page: number): Point {
  const taken = comments.filter((c) => c.page === page && c.type === "Text").map((c) => c.rect);
  for (let slot = 0; slot < 40; slot++) {
    const offset = (slot % 20) * NOTE_STEP;
    const x = NOTE_ORIGIN + offset;
    const y = NOTE_ORIGIN + offset;
    if (!taken.some((rect) => Math.abs(rect[0] - x) < NOTE_STEP / 2 && Math.abs(rect[1] - y) < NOTE_STEP / 2)) return [x, y];
  }
  return [NOTE_ORIGIN, NOTE_ORIGIN];
}

/** "3 of 12 comments" while filtering, else "12 comments, 4 replies". ``total`` counts comments and replies. */
export function countLabel(shown: number, comments: number, total: number, filtering: boolean): string {
  if (filtering) return `${shown} of ${comments} comment${comments === 1 ? "" : "s"}`;
  const replies = Math.max(0, total - comments);
  const base = `${comments} comment${comments === 1 ? "" : "s"}`;
  return replies ? `${base}, ${replies} repl${replies === 1 ? "y" : "ies"}` : base;
}

/** One line for the toast after an XFDF import. */
export function summarizeImport(result: XfdfImportResult): string {
  const parts = [
    result.added && `${result.added} added`,
    result.updated && `${result.updated} updated`,
    result.unchanged && `${result.unchanged} already there`,
    result.skipped && `${result.skipped} skipped`,
  ].filter(Boolean);
  return parts.length ? `Comments imported: ${parts.join(", ")}` : "The file has no comments to import";
}
