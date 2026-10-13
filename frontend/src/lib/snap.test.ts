import { describe, expect, it } from "vitest";
import { snapBox, snapEdge, snapTargets } from "./snap";

const page = { width: 600, height: 800 };
const targets = snapTargets([[72, 100, 300, 114], [320, 200, 500, 214]], page);

describe("snapTargets", () => {
  it("collects edges, centres and the page centre", () => {
    expect(targets.xs).toEqual(expect.arrayContaining([72, 300, 186, 320, 500, 410, 300]));
    expect(targets.ys).toEqual(expect.arrayContaining([100, 114, 200, 214, 400]));
  });
});

describe("snapBox", () => {
  it("snaps the left edge to nearby text", () => {
    const result = snapBox({ x: 74, y: 150, width: 100, height: 14 }, targets, 4);
    expect(result.x).toBe(72);
    expect(result.guides.x).toBe(72);
  });

  it("snaps the centre to the page centre", () => {
    const result = snapBox({ x: 248.5, y: 500, width: 100, height: 14 }, targets, 4);
    expect(result.x).toBe(250);
    expect(result.guides.x).toBe(300);
  });

  it("snaps the top edge vertically", () => {
    const result = snapBox({ x: 10, y: 198, width: 50, height: 14 }, targets, 4);
    expect(result.y).toBe(200);
    expect(result.guides.y).toBe(200);
  });

  it("leaves the box alone when nothing is close", () => {
    const result = snapBox({ x: 20, y: 600, width: 10, height: 10 }, targets, 4);
    expect(result).toEqual({ x: 20, y: 600, guides: {} });
  });
});

describe("snapEdge", () => {
  it("snaps a dragged edge", () => {
    expect(snapEdge(497, targets.xs, 4)).toEqual({ value: 500, guide: 500 });
    expect(snapEdge(560, targets.xs, 4)).toEqual({ value: 560, guide: undefined });
  });
});
