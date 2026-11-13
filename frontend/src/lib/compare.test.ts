import { describe, expect, it } from "vitest";
import type { ChangeKind, ChangeType, CompareChange, ComparePair, CompareReport } from "../api/compareTypes";
import {
  ALL_FILTERS,
  PAD_TOP,
  ROW_GAP,
  ROW_HEADER,
  allChanges,
  changeDetail,
  changeLabel,
  clip,
  columnWidth,
  countByFilter,
  fitZoom,
  highlightBox,
  highlightsFor,
  isStale,
  pageRef,
  renderScale,
  rowLayout,
  scrollTarget,
  stepChange,
  summaryText,
  visibleChanges,
  visibleRange,
} from "./compare";

function change(id: string, pair: number, kind: ChangeKind, type: ChangeType, extra: Partial<CompareChange> = {}): CompareChange {
  return {
    id, kind, type, pair, pageA: pair, pageB: pair, oldText: "", newText: "", before: "", after: "",
    rectsA: [], rectsB: [], anchorA: null, anchorB: null, ...extra,
  };
}

function pairOf(index: number, changes: CompareChange[], size: [number, number] = [600, 800]): ComparePair {
  return {
    index, pageA: index, pageB: index, status: changes.length ? "changed" : "matched", similarity: 1,
    sizeA: size, sizeB: size, sizeChanged: false, text: null, visual: null, changes,
  };
}

const replaced = change("c0", 0, "text", "replace", { oldText: "wording", newText: "phrasing", rectsA: [[72, 150, 120, 164]], rectsB: [[72, 150, 130, 164]] });
const inserted = change("c1", 0, "text", "insert", { newText: "extra words", rectsB: [[72, 200, 160, 214]], anchorA: [90, 200, 90, 214] });
const deleted = change("c2", 2, "text", "delete", { oldText: "gone", rectsA: [[72, 300, 100, 314]], anchorB: [80, 300, 80, 314] });
const region = change("c3", 2, "visual", "region", { rectsA: [[300, 400, 450, 500]], rectsB: [[300, 400, 450, 500]], pixels: 1200 });
const added = change("c4", 3, "page", "insert", { pageA: null, newText: "Brand new page", rectsB: [[0, 0, 600, 800]] });

function report(...changes: CompareChange[]): CompareReport {
  const pairs = [0, 1, 2, 3].map((index) => pairOf(index, changes.filter((c) => c.pair === index)));
  return {
    options: { mode: "both", dpi: 72, sensitivity: "medium", ignoreCase: false },
    pairs, baseVersion: "v0002.pdf", base: { filename: "a.pdf", pages: 3 }, other: { filename: "b.pdf", pages: 4 },
    totals: {
      pairs: 4, matched: 1, changed: 2, inserted: 1, removed: 0, changes: changes.length, textChanges: 0, visualChanges: 0,
      pageChanges: 0, pagesWithChanges: 3, wordsInserted: 0, wordsDeleted: 0,
    },
  };
}

const full = report(replaced, inserted, deleted, region, added);

describe("filters", () => {
  it("lists every change in reading order", () => {
    expect(allChanges(full).map((c) => c.id)).toEqual(["c0", "c1", "c2", "c3", "c4"]);
    expect(allChanges(null)).toEqual([]);
  });

  it("filters by text, image and page changes", () => {
    expect(visibleChanges(full, { ...ALL_FILTERS, text: false }).map((c) => c.id)).toEqual(["c3", "c4"]);
    expect(visibleChanges(full, { text: false, image: true, page: false }).map((c) => c.id)).toEqual(["c3"]);
    expect(visibleChanges(full, { text: true, image: false, page: false }).map((c) => c.id)).toEqual(["c0", "c1", "c2"]);
    expect(visibleChanges(full, { text: false, image: false, page: false })).toEqual([]);
  });

  it("counts changes per type for the filter buttons", () => {
    expect(countByFilter(full)).toEqual({ text: 3, image: 1, page: 1 });
    expect(countByFilter(null)).toEqual({ text: 0, image: 0, page: 0 });
  });
});

describe("summary header", () => {
  it("says how many changes there are and on how many pages", () => {
    expect(summaryText(allChanges(full))).toBe("5 changes across 3 pages");
    expect(summaryText([replaced, inserted])).toBe("2 changes across 1 page");
    expect(summaryText([deleted])).toBe("1 change across 1 page");
  });

  it("follows the filter", () => {
    expect(summaryText(visibleChanges(full, { text: false, image: true, page: false }))).toBe("1 change across 1 page");
  });

  it("reports an identical comparison", () => {
    expect(summaryText([])).toBe("No differences found");
  });
});

describe("wording", () => {
  it("names each kind of change", () => {
    expect(changeLabel(replaced)).toBe("Replaced");
    expect(changeLabel(inserted)).toBe("Added");
    expect(changeLabel(deleted)).toBe("Deleted");
    expect(changeLabel(region)).toBe("Image or layout");
    expect(changeLabel(added)).toBe("Page added");
    expect(changeLabel(change("x", 0, "page", "delete"))).toBe("Page removed");
    expect(changeLabel(change("x", 0, "page", "resize"))).toBe("Page size");
  });

  it("shows what changed", () => {
    expect(changeDetail(replaced)).toBe("wording → phrasing");
    expect(changeDetail(inserted)).toBe("extra words");
    expect(changeDetail(deleted)).toBe("gone");
    expect(changeDetail(change("p", 1, "page", "resize", { oldText: "612 x 792 pt", newText: "595 x 842 pt" }))).toBe("612 x 792 pt → 595 x 842 pt");
    expect(changeDetail(change("p", 1, "page", "insert", { pageA: null }))).toBe("Page without text");
  });

  it("shortens long text without breaking words into the next line", () => {
    expect(clip("one   two\nthree", 50)).toBe("one two three");
    expect(clip("abcdefghij", 6)).toBe("abcde…");
    expect(changeDetail(change("l", 0, "text", "insert", { newText: "word ".repeat(60) }), 40).length).toBeLessThanOrEqual(40);
  });

  it("points at the page, or at both page numbers when they differ", () => {
    expect(pageRef(replaced)).toBe("Page 1");
    expect(pageRef(change("m", 1, "text", "insert", { pageA: 1, pageB: 2 }))).toBe("Page 2 → 3");
    expect(pageRef(added)).toBe("New page 4");
  });
});

describe("jumping between changes", () => {
  const list = allChanges(full);

  it("steps forward and backward", () => {
    expect(stepChange(list, "c1", 1)?.id).toBe("c2");
    expect(stepChange(list, "c1", -1)?.id).toBe("c0");
  });

  it("wraps around at both ends", () => {
    expect(stepChange(list, "c4", 1)?.id).toBe("c0");
    expect(stepChange(list, "c0", -1)?.id).toBe("c4");
  });

  it("starts at the first or last change when none is active, or the active one was filtered out", () => {
    expect(stepChange(list, null, 1)?.id).toBe("c0");
    expect(stepChange(list, null, -1)?.id).toBe("c4");
    expect(stepChange(list, "gone", 1)?.id).toBe("c0");
  });

  it("has nowhere to go without changes", () => {
    expect(stepChange([], null, 1)).toBeNull();
    expect(stepChange([], "c0", -1)).toBeNull();
  });
});

describe("page rows", () => {
  const pairs = [pairOf(0, []), pairOf(1, [], [400, 1000]), pairOf(2, [])];

  it("makes every row as tall as the taller page and stacks them", () => {
    const layout = rowLayout(pairs, 0.5);
    expect(layout.heights).toEqual([ROW_HEADER + 400, ROW_HEADER + 500, ROW_HEADER + 400]);
    expect(layout.offsets[0]).toBe(PAD_TOP);
    expect(layout.offsets[1]).toBe(PAD_TOP + ROW_HEADER + 400 + ROW_GAP);
    expect(layout.total).toBe(layout.offsets[2] + layout.heights[2] + ROW_GAP + PAD_TOP);
  });

  it("uses the larger page of an inserted page's partner", () => {
    const solo: ComparePair = { ...pairOf(0, []), pageA: null, sizeA: null, sizeB: [300, 500] };
    expect(rowLayout([solo], 1).heights).toEqual([ROW_HEADER + 500]);
  });

  it("gives both columns the width of the widest page", () => {
    expect(columnWidth(pairs, 0.5)).toBe(300);
    expect(columnWidth([], 1)).toBe(0);
  });

  it("finds the rows to draw for the visible part of the scroll area", () => {
    const layout = rowLayout(pairs, 1);
    expect(visibleRange(layout, 0, 300, 0)).toEqual([0, 0]);
    expect(visibleRange(layout, 0, 300, 2000)).toEqual([0, 2]);
    const second = layout.offsets[1];
    expect(visibleRange(layout, second + 10, 100, 0)).toEqual([1, 1]);
    expect(visibleRange(layout, 100000, 100, 0)).toEqual([0, -1]);
    expect(visibleRange(rowLayout([], 1), 0, 100, 0)).toEqual([0, -1]);
  });

  it("fits both columns into the viewport width", () => {
    const zoom = fitZoom(pairs, 1260);
    expect(zoom).toBeCloseTo((1260 - 40 - 20) / 1200, 5);
    expect(fitZoom([], 1000)).toBe(1);
    expect(fitZoom(pairs, 10)).toBeGreaterThanOrEqual(0.2);
    expect(fitZoom([pairOf(0, [], [10, 10])], 5000)).toBeLessThanOrEqual(4);
  });

  it("asks for images in eighths and caps the scale", () => {
    expect(renderScale(1)).toBe(1);
    expect(renderScale(0.93, 1)).toBe(0.875);
    expect(renderScale(1, 2)).toBe(2);
    expect(renderScale(5, 3)).toBe(8);
    expect(renderScale(0.01)).toBe(0.125);
  });
});

describe("highlights", () => {
  const ids = (list: ReturnType<typeof highlightsFor>) => list.map((h) => `${h.changeId}:${h.tone}${h.marker ? ":marker" : ""}`);

  it("marks replaced words on both sides", () => {
    expect(ids(highlightsFor([replaced], "a", null))).toEqual(["c0:replace-old"]);
    expect(ids(highlightsFor([replaced], "b", null))).toEqual(["c0:replace-new"]);
  });

  it("marks added words on the revised side and the place they were added to on the original", () => {
    expect(ids(highlightsFor([inserted], "b", null))).toEqual(["c1:insert"]);
    expect(ids(highlightsFor([inserted], "a", null))).toEqual(["c1:insert:marker"]);
  });

  it("marks deleted words on the original side and the place they were removed from on the revised one", () => {
    expect(ids(highlightsFor([deleted], "a", null))).toEqual(["c2:delete"]);
    expect(ids(highlightsFor([deleted], "b", null))).toEqual(["c2:delete:marker"]);
  });

  it("marks a changed area on both sides", () => {
    expect(ids(highlightsFor([region], "a", null))).toEqual(["c3:visual"]);
    expect(ids(highlightsFor([region], "b", null))).toEqual(["c3:visual"]);
  });

  it("tints an added page only where it exists", () => {
    expect(ids(highlightsFor([added], "b", null))).toEqual(["c4:page-insert"]);
    expect(highlightsFor([added], "a", null)).toEqual([]);
    const removed = change("c5", 1, "page", "delete", { pageB: null, rectsA: [[0, 0, 600, 800]] });
    expect(ids(highlightsFor([removed], "a", null))).toEqual(["c5:page-delete"]);
    expect(highlightsFor([removed], "b", null)).toEqual([]);
  });

  it("draws nothing for a changed page size", () => {
    expect(highlightsFor([change("r", 0, "page", "resize")], "a", null)).toEqual([]);
  });

  it("flags only the active change", () => {
    const list = highlightsFor([replaced, inserted], "b", "c1");
    expect(list.map((h) => [h.changeId, h.active])).toEqual([["c0", false], ["c1", true]]);
  });

  it("gives every highlight its own key", () => {
    const wrapped = change("w", 0, "text", "replace", { rectsA: [[1, 1, 5, 5], [1, 9, 5, 13]], rectsB: [] });
    const keys = highlightsFor([wrapped], "a", null).map((h) => h.key);
    expect(new Set(keys).size).toBe(2);
  });

  it("scales boxes with the zoom and gives insertion points a visible width", () => {
    const [word] = highlightsFor([replaced], "b", null);
    expect(highlightBox(word, 2)).toEqual({ left: 144, top: 300, width: 116, height: 28 });
    const [point] = highlightsFor([inserted], "a", null);
    const box = highlightBox(point, 2);
    expect(box.width).toBe(3);
    expect(box.left).toBeCloseTo(180 - 1.5);
    expect(box.height).toBe(28);
  });
});

describe("scrolling to a change", () => {
  const layout = rowLayout([0, 1, 2, 3].map((i) => pairOf(i, [])), 1);

  it("puts a change a third of the way down the viewport", () => {
    const target = scrollTarget(layout, deleted, 1, 600);
    expect(target).toBe(layout.offsets[2] + ROW_HEADER + 300 - 180);
  });

  it("shows the start of the row for a whole-page change", () => {
    expect(scrollTarget(layout, added, 1, 600)).toBe(layout.offsets[3] - PAD_TOP);
  });

  it("never scrolls above the top", () => {
    expect(scrollTarget(layout, replaced, 1, 3000)).toBe(0);
    expect(scrollTarget(layout, change("z", 99, "text", "insert"), 1, 600)).toBe(0);
  });
});

describe("a report that no longer matches the document", () => {
  it("is stale once the document has another version", () => {
    expect(isStale(full, "v0002.pdf")).toBe(false);
    expect(isStale(full, "v0003.pdf")).toBe(true);
    expect(isStale(null, "v0003.pdf")).toBe(false);
    expect(isStale(full, undefined)).toBe(false);
  });
});
