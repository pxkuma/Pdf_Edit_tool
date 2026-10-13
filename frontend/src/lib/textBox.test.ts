import { describe, expect, it } from "vitest";
import type { Rect, Span, TextBlock, TextLine } from "../api/types";
import { autoBox, freeSpan, scaleBox, textBoxLines, widenBox } from "./textBox";

const page = { width: 612, height: 792 };
const name: Rect = [72, 100, 120, 114]; // a short single-line "name" block

describe("freeSpan", () => {
  it("extends to the page margin when nothing is beside the box", () => {
    const span = freeSpan(name, [{ id: "a", bbox: name }], "a", page);
    expect(span.right).toBe(612 - 72);
    expect(span.left).toBe(72);
  });

  it("stops before a block on the same line", () => {
    const value: Rect = [300, 101, 360, 113];
    const span = freeSpan(name, [{ id: "a", bbox: name }, { id: "b", bbox: value }], "a", page);
    expect(span.right).toBeLessThan(300);
    expect(span.right).toBeGreaterThan(290);
  });

  it("ignores blocks on other lines", () => {
    const below: Rect = [200, 140, 400, 154];
    const span = freeSpan(name, [{ id: "a", bbox: name }, { id: "b", bbox: below }], "a", page);
    expect(span.right).toBe(612 - 72);
  });

  it("never shrinks below the original box", () => {
    const wide: Rect = [20, 100, 600, 114];
    const span = freeSpan(wide, [{ id: "a", bbox: wide }], "a", page);
    expect(span.left).toBeLessThanOrEqual(20);
    expect(span.right).toBeGreaterThanOrEqual(600);
  });
});

describe("autoBox", () => {
  const free = { left: 72, right: 540 };

  it("keeps the original width for shorter text", () => {
    expect(autoBox(name, 30, free, "left")).toEqual({ x: 72, width: 48 });
  });

  it("grows to the right for longer left-aligned text instead of wrapping", () => {
    const box = autoBox(name, 200, free, "left");
    expect(box.x).toBe(72);
    expect(box.width).toBeGreaterThanOrEqual(200);
  });

  it("is capped by the free space", () => {
    expect(autoBox(name, 900, free, "left")).toEqual({ x: 72, width: 468 });
  });

  it("grows to the left for right-aligned text", () => {
    const box = autoBox(name, 100, { left: 18, right: 540 }, "right");
    expect(box.x + box.width).toBeCloseTo(120);
    expect(box.width).toBeGreaterThanOrEqual(100);
  });

  it("grows evenly for centred text", () => {
    const box = autoBox(name, 100, { left: 18, right: 540 }, "center");
    expect(box.x + box.width / 2).toBeCloseTo(96);
    expect(box.width).toBeGreaterThanOrEqual(100);
  });
});

describe("widenBox", () => {
  it("resizes from the right edge", () => {
    expect(widenBox({ x: 10, width: 100 }, "e", 40)).toEqual({ x: 10, width: 140 });
  });

  it("resizes from the left edge keeping the right edge", () => {
    expect(widenBox({ x: 10, width: 100 }, "w", 30)).toEqual({ x: 40, width: 70 });
  });

  it("has a minimum width", () => {
    expect(widenBox({ x: 10, width: 100 }, "e", -500).width).toBe(12);
  });
});

describe("scaleBox", () => {
  it("scales size and width from the bottom-right corner", () => {
    const next = scaleBox({ x: 10, width: 100 }, 12, "se", 50);
    expect(next.size).toBe(18);
    expect(next.box).toEqual({ x: 10, width: 150 });
  });

  it("keeps the right edge when scaling from the bottom-left corner", () => {
    const next = scaleBox({ x: 10, width: 100 }, 12, "sw", 50);
    expect(next.size).toBe(6);
    expect(next.box.x + next.box.width).toBe(110);
  });

  it("clamps the font size", () => {
    expect(scaleBox({ x: 0, width: 100 }, 12, "se", -99).size).toBe(1);
  });
});

function line(id: string, x0: number, baseline: number, x1: number, size = 12): TextLine {
  const span = { id: `s${id}`, origin: [x0, baseline], size, bbox: [x0, baseline - size * 0.8, x1, baseline + size * 0.2], text: id } as unknown as Span;
  return { id, bbox: span.bbox, dir: [1, 0], spans: [span] };
}

describe("textBoxLines", () => {
  it("keeps a label and its value apart when they share a baseline", () => {
    const block: TextBlock = { id: "b", bbox: [72, 90, 150, 102], lines: [line("Name:", 72, 100, 105), line("Ravi", 120, 100, 145)] };
    const box = textBoxLines(block, "Ravi");
    expect(box.lines.map((l) => l.id)).toEqual(["Ravi"]);
    expect(box.bbox[0]).toBe(120);
  });

  it("takes the whole paragraph around the clicked line", () => {
    const block: TextBlock = {
      id: "p",
      bbox: [72, 90, 400, 132],
      lines: [line("one", 72, 100, 400), line("two", 72, 115, 390), line("three", 72, 130, 200)],
    };
    expect(textBoxLines(block, "two").lines.map((l) => l.id)).toEqual(["one", "two", "three"]);
  });

  it("does not pull in a table row below a paragraph line", () => {
    const block: TextBlock = {
      id: "t",
      bbox: [72, 90, 420, 132],
      lines: [line("title", 72, 100, 300), line("Item", 72, 130, 100), line("Amount", 360, 130, 420)],
    };
    expect(textBoxLines(block, "title").lines.map((l) => l.id)).toEqual(["title"]);
    expect(textBoxLines(block, "Amount").lines.map((l) => l.id)).toEqual(["Amount"]);
  });

  it("stops at a large vertical gap", () => {
    const block: TextBlock = { id: "g", bbox: [72, 90, 300, 200], lines: [line("a", 72, 100, 300), line("b", 72, 190, 300)] };
    expect(textBoxLines(block, "a").lines.map((l) => l.id)).toEqual(["a"]);
  });
});
