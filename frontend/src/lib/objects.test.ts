import { describe, expect, it } from "vitest";
import type { PageModel, Rect, Span, TextLine } from "../api/types";
import { moveRect, objectFromSelection, pageObjects, resizeObject, sameObject, selectionOf, textBoxes } from "./objects";

function span(id: string, bbox: Rect, extra: Partial<Span> = {}): Span {
  return { id, text: id, bbox, origin: [bbox[0], bbox[3] - 2], size: 12, font: "Arial", color: "#000000", bold: false, italic: false, ...extra } as Span;
}

function line(id: string, spans: Span[]): TextLine {
  const bbox: Rect = [Math.min(...spans.map((s) => s.bbox[0])), spans[0].bbox[1], Math.max(...spans.map((s) => s.bbox[2])), spans[0].bbox[3]];
  return { id, bbox, dir: [1, 0], spans };
}

const model = {
  text: {
    blocks: [
      { id: "0", bbox: [72, 90, 300, 132], lines: [line("0-0", [span("a", [72, 90, 300, 104])]), line("0-1", [span("b", [72, 105, 280, 118])])] },
      {
        id: "1",
        bbox: [72, 150, 420, 162],
        lines: [line("1-0", [span("c", [72, 150, 96, 162])]), line("1-1", [span("d", [360, 150, 420, 162], { bold: true })])],
      },
    ],
    words: [],
  },
  images: [{ xref: 7, bbox: [300, 300, 400, 380], editable: true }],
  drawings: [[72, 200, 540, 200]] as Rect[],
  annotations: [],
  fields: [],
} as unknown as PageModel;

describe("textBoxes", () => {
  it("groups paragraph lines and splits row cells", () => {
    const boxes = textBoxes(model);
    expect(boxes.map((b) => b.block.lines.map((l) => l.id))).toEqual([["0-0", "0-1"], ["1-0"], ["1-1"]]);
  });

  it("knows whether a box has one style", () => {
    const mixed = textBoxes({
      ...model,
      text: { ...model.text, blocks: [{ id: "x", bbox: [0, 0, 100, 10], lines: [line("x-0", [span("e", [0, 0, 50, 10]), span("f", [50, 0, 100, 10], { color: "#ff0000" })])] }] },
    } as PageModel);
    expect(mixed[0].uniform).toBe(false);
    expect(textBoxes(model)[0].uniform).toBe(true);
  });
});

describe("pageObjects", () => {
  it("lists images and drawings with a grabbable size", () => {
    const objects = pageObjects(model);
    expect(objects.map((o) => o.kind)).toEqual(["drawing", "image"]);
    const rule = objects[0];
    expect(rule.hit[3] - rule.hit[1]).toBeGreaterThanOrEqual(6);
  });
});

describe("resizeObject", () => {
  const rect: Rect = [100, 100, 200, 150];

  it("stretches freely from a side handle", () => {
    expect(resizeObject(rect, "e", 50, 30, true)).toEqual([100, 100, 250, 150]);
  });

  it("keeps proportions from a corner when asked", () => {
    const next = resizeObject(rect, "se", 100, 0, true);
    expect(next).toEqual([100, 100, 300, 200]);
  });

  it("anchors the opposite corner", () => {
    const next = resizeObject(rect, "nw", -100, 0, true);
    expect(next[2]).toBe(200);
    expect(next[3]).toBe(150);
    expect(next[2] - next[0]).toBe(200);
  });

  it("resizes freely from a corner otherwise", () => {
    expect(resizeObject(rect, "se", 10, 40, false)).toEqual([100, 100, 210, 190]);
  });
});

describe("moveRect", () => {
  it("is not limited by the page", () => {
    expect(moveRect([10, 10, 20, 20], -50, 900)).toEqual([-40, 910, -30, 920]);
  });
});

describe("selection round trip", () => {
  it("turns a page object into a selection and back", () => {
    const [rule, image] = pageObjects(model);
    for (const object of [rule, image]) {
      const back = objectFromSelection(selectionOf(object, 3), 3);
      expect(back && sameObject(back, object)).toBe(true);
      expect(objectFromSelection(selectionOf(object, 3), 4)).toBeNull();
    }
  });
});
