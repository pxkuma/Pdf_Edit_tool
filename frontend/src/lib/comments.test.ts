import { describe, expect, it } from "vitest";
import type { CommentReply, PdfComment, XfdfImportResult } from "../api/types";
import {
  NO_FILTER,
  countLabel,
  filterComments,
  groupComments,
  initials,
  isFiltering,
  lastActivity,
  matchesFilter,
  nextNotePosition,
  presentTypes,
  relativeTime,
  sortComments,
  summarizeImport,
  threadAuthors,
  typeLabel,
} from "./comments";

let counter = 0;

function comment(extra: Partial<PdfComment> = {}): PdfComment {
  counter += 1;
  return {
    id: `0:${counter}`,
    page: 0,
    xref: counter,
    name: `n${counter}`,
    type: "Text",
    author: "Alice",
    subject: "",
    contents: "",
    created: "2026-03-01T10:00:00Z",
    modified: "2026-03-01T10:00:00Z",
    color: null,
    rect: [100, 100, 116, 116],
    quote: "",
    status: "none",
    statusBy: "",
    statusDate: "",
    checked: false,
    parent: null,
    replies: [],
    ...extra,
  };
}

function reply(extra: Partial<CommentReply> = {}): CommentReply {
  const { replies: _unused, ...base } = comment() as PdfComment;
  return { ...base, depth: 1, parent: 1, author: "Bob", ...extra };
}

const alice = comment({ xref: 1, page: 0, contents: "Fix the figure", author: "Alice", rect: [50, 300, 66, 316] });
const bob = comment({
  xref: 2, page: 0, type: "Highlight", author: "Bob", quote: "annual revenue", status: "accepted",
  rect: [50, 100, 120, 114], modified: "2026-03-03T09:00:00Z", created: "2026-03-03T09:00:00Z",
});
const carol = comment({
  xref: 3, page: 2, type: "FreeText", author: "", contents: "Unsigned remark", status: "rejected",
  modified: "2026-03-02T09:00:00Z", created: "2026-03-02T09:00:00Z",
});
const dan = comment({
  xref: 4, page: 1, author: "Dan", contents: "Question about totals", status: "completed",
  replies: [reply({ author: "Alice", contents: "Totals are in table 2", modified: "2026-03-05T12:00:00Z", created: "2026-03-05T12:00:00Z" })],
});
const all = [alice, bob, carol, dan];

describe("labels", () => {
  it("name PDF types the way people say them, and pass unknown ones through", () => {
    expect(typeLabel("Text")).toBe("Note");
    expect(typeLabel("StrikeOut")).toBe("Strikeout");
    expect(typeLabel("FreeText")).toBe("Text box");
    expect(typeLabel("Widget")).toBe("Widget");
  });

  it("make initials of one or several words", () => {
    expect(initials("Alice")).toBe("AL");
    expect(initials("Alice Marie Smith")).toBe("AS");
    expect(initials("  ")).toBe("?");
    expect(initials("élodie")).toBe("ÉL");
  });
});

describe("thread facts", () => {
  it("lists everyone who took part once", () => {
    expect(threadAuthors(dan).sort()).toEqual(["Alice", "Dan"]);
    expect(threadAuthors(carol)).toEqual([]);
  });

  it("finds the latest change in a thread, replies included", () => {
    expect(lastActivity(dan)).toBe("2026-03-05T12:00:00Z");
    expect(lastActivity(bob)).toBe("2026-03-03T09:00:00Z");
  });
});

describe("filtering", () => {
  it("keeps everything when no filter is set", () => {
    expect(isFiltering(NO_FILTER)).toBe(false);
    expect(filterComments(all, NO_FILTER)).toBe(all);
    expect(isFiltering({ ...NO_FILTER, query: "   " })).toBe(false);
  });

  it("filters by author, also finding threads the author only replied in", () => {
    expect(filterComments(all, { ...NO_FILTER, author: "Bob" })).toEqual([bob]);
    expect(filterComments(all, { ...NO_FILTER, author: "Alice" })).toEqual([alice, dan]);
  });

  it("filters by type and by status", () => {
    expect(filterComments(all, { ...NO_FILTER, type: "Highlight" })).toEqual([bob]);
    expect(filterComments(all, { ...NO_FILTER, status: "rejected" })).toEqual([carol]);
    expect(filterComments(all, { ...NO_FILTER, status: "none" })).toEqual([alice]);
  });

  it("searches comment text, quoted text, authors and replies without caring about case", () => {
    expect(filterComments(all, { ...NO_FILTER, query: "FIGURE" })).toEqual([alice]);
    expect(filterComments(all, { ...NO_FILTER, query: "revenue" })).toEqual([bob]);
    expect(filterComments(all, { ...NO_FILTER, query: "table 2" })).toEqual([dan]);
    expect(filterComments(all, { ...NO_FILTER, query: "dan" })).toEqual([dan]);
  });

  it("combines criteria", () => {
    expect(filterComments(all, { author: "Alice", type: "Text", status: "completed", query: "totals" })).toEqual([dan]);
    expect(matchesFilter(alice, { ...NO_FILTER, author: "Alice", status: "accepted" })).toBe(false);
  });

  it("returns nothing when nothing matches", () => {
    expect(filterComments(all, { ...NO_FILTER, query: "zebra" })).toEqual([]);
  });
});

describe("sorting", () => {
  it("orders by page, then top to bottom, then left to right", () => {
    expect(sortComments(all, "page").map((c) => c.xref)).toEqual([2, 1, 4, 3]);
  });

  it("orders by the newest activity first, so a fresh reply lifts a thread", () => {
    expect(sortComments(all, "date").map((c) => c.xref)).toEqual([4, 2, 3, 1]);
  });

  it("orders by author name, unsigned comments last", () => {
    expect(sortComments(all, "author").map((c) => c.author)).toEqual(["Alice", "Bob", "Dan", ""]);
  });

  it("does not change the list it is given", () => {
    const before = all.map((c) => c.xref);
    sortComments(all, "date");
    expect(all.map((c) => c.xref)).toEqual(before);
  });
});

describe("grouping", () => {
  it("groups by page in page order", () => {
    const groups = groupComments(sortComments(all, "page"), "page");
    expect(groups.map((g) => [g.title, g.comments.map((c) => c.xref)])).toEqual([
      ["Page 1", [2, 1]],
      ["Page 2", [4]],
      ["Page 3", [3]],
    ]);
  });

  it("groups by author, with a heading for unsigned comments", () => {
    const groups = groupComments(sortComments(all, "author"), "author");
    expect(groups.map((g) => g.title)).toEqual(["Alice", "Bob", "Dan", "Unknown"]);
  });

  it("groups by the day of the latest activity", () => {
    const now = new Date(2026, 2, 6, 8, 0);
    const local = (day: number, hour = 12) => new Date(2026, 2, day, hour).toISOString();
    const items = [
      comment({ xref: 10, modified: local(6), created: local(6) }),
      comment({ xref: 11, modified: local(5), created: local(5) }),
      comment({ xref: 12, modified: local(5, 9), created: local(5, 9) }),
      comment({ xref: 13, modified: local(1), created: local(1) }),
      comment({ xref: 14, modified: "", created: "" }),
    ];
    const groups = groupComments(sortComments(items, "date"), "date", now);
    expect(groups.map((g) => [g.title, g.comments.map((c) => c.xref)])).toEqual([
      ["Today", [10]],
      ["Yesterday", [11, 12]],
      ["Mar 1, 2026", [13]],
      ["No date", [14]],
    ]);
  });

  it("gives no groups for no comments", () => {
    expect(groupComments([], "page")).toEqual([]);
  });
});

describe("type menu", () => {
  it("lists the types that occur, in a steady order", () => {
    expect(presentTypes(all)).toEqual(["Text", "Highlight", "FreeText"]);
    expect(presentTypes([comment({ type: "Mystery" }), comment({ type: "Ink" })])).toEqual(["Ink", "Mystery"]);
  });
});

describe("relative times", () => {
  const now = new Date("2026-03-10T12:00:00Z");

  it("speaks in minutes, hours and days, then gives the date", () => {
    expect(relativeTime("2026-03-10T11:59:50Z", now)).toBe("just now");
    expect(relativeTime("2026-03-10T11:55:00Z", now)).toBe("5 min ago");
    expect(relativeTime("2026-03-10T09:00:00Z", now)).toBe("3 h ago");
    expect(relativeTime("2026-03-08T12:00:00Z", now)).toBe("2 d ago");
    expect(relativeTime("2026-01-02T12:00:00Z", now)).toMatch(/^Jan \d, 2026$/);
  });

  it("is empty for a missing or broken date and never negative", () => {
    expect(relativeTime("", now)).toBe("");
    expect(relativeTime("not a date", now)).toBe("");
    expect(relativeTime("2026-03-11T00:00:00Z", now)).toBe("just now");
  });
});

describe("placing a quick note", () => {
  it("starts in the top-left corner of the page", () => {
    expect(nextNotePosition([], 0)).toEqual([36, 36]);
  });

  it("steps along the diagonal past notes that are already there", () => {
    const here = [comment({ rect: [36, 36, 52, 52] }), comment({ rect: [60, 60, 76, 76] })];
    expect(nextNotePosition(here, 0)).toEqual([84, 84]);
  });

  it("ignores other pages and other kinds of comment", () => {
    const elsewhere = [comment({ page: 1, rect: [36, 36, 52, 52] }), comment({ type: "Highlight", rect: [36, 36, 52, 52] })];
    expect(nextNotePosition(elsewhere, 0)).toEqual([36, 36]);
  });
});

describe("count line", () => {
  it("counts comments and replies, or the share that passes the filters", () => {
    expect(countLabel(12, 12, 16, false)).toBe("12 comments, 4 replies");
    expect(countLabel(1, 1, 2, false)).toBe("1 comment, 1 reply");
    expect(countLabel(3, 3, 3, false)).toBe("3 comments");
    expect(countLabel(2, 9, 20, true)).toBe("2 of 9 comments");
    expect(countLabel(0, 1, 1, true)).toBe("0 of 1 comment");
  });
});

describe("import summary", () => {
  const result = (extra: Partial<XfdfImportResult>): XfdfImportResult => ({
    added: 0, updated: 0, unchanged: 0, skipped: 0, warnings: [], pages: [], ...extra,
  });

  it("names what happened", () => {
    expect(summarizeImport(result({ added: 3, updated: 1, skipped: 2 }))).toBe("Comments imported: 3 added, 1 updated, 2 skipped");
    expect(summarizeImport(result({ unchanged: 4 }))).toBe("Comments imported: 4 already there");
  });

  it("says so when the file held nothing", () => {
    expect(summarizeImport(result({}))).toBe("The file has no comments to import");
  });
});
