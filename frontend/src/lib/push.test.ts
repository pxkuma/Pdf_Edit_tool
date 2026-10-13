import { describe, expect, it } from "vitest";
import type { Rect } from "../api/types";
import { boxGrowth, pushConflicts, selectPush, type PushCandidate } from "./push";

const page = { width: 600, height: 800 };
const box: Rect = [72, 90, 300, 104];
const item = (key: string, bbox: Rect): PushCandidate => ({ key, kind: "text", bbox });

describe("selectPush", () => {
  const below = item("below", [72, 120, 280, 132]);
  const beside = item("beside", [400, 120, 520, 132]);
  const above = item("above", [72, 60, 280, 72]);
  const rule = item("rule", [72, 150, 540, 151]);
  const underRule = item("underRule", [400, 170, 520, 182]);
  const footer = item("footer", [72, 770, 200, 780]);
  const all = [below, beside, above, rule, underRule, footer];

  it("moves what is below the box in its column, cascading through wider items", () => {
    const { moving } = selectPush(all, box, [72, 300], { scope: "column", overrides: {} }, page);
    expect(moving.map((m) => m.key)).toEqual(["below", "rule", "underRule"]);
  });

  it("moves everything below in full-width scope, except the footer", () => {
    const { moving, kept } = selectPush(all, box, [72, 300], { scope: "page", overrides: {} }, page);
    expect(moving.map((m) => m.key)).toEqual(["below", "beside", "rule", "underRule"]);
    expect(kept.map((m) => m.key)).toContain("footer");
  });

  it("lets the user pin an item, which then stops the cascade through it", () => {
    const { moving, kept } = selectPush(all, box, [72, 300], { scope: "column", overrides: { rule: false } }, page);
    expect(moving.map((m) => m.key)).toEqual(["below"]);
    expect(kept.map((m) => m.key)).toContain("rule");
  });

  it("lets the user include any item below", () => {
    const { moving } = selectPush(all, box, [72, 300], { scope: "column", overrides: { beside: true, footer: true } }, page);
    expect(moving.map((m) => m.key)).toContain("beside");
    expect(moving.map((m) => m.key)).toContain("footer");
  });

  it("never moves things above the box", () => {
    const { moving, kept } = selectPush(all, box, [72, 300], { scope: "page", overrides: { above: true } }, page);
    expect(moving.map((m) => m.key)).not.toContain("above");
    expect(kept.map((m) => m.key)).not.toContain("above");
  });
});

describe("boxGrowth", () => {
  it("is the extra height of added lines", () => {
    expect(boxGrowth({ rows: 3, lines: 1, step: 14, originalStep: 14, size: 12, originalSize: 12 })).toBeCloseTo(28);
  });

  it("is negative when the box gets shorter", () => {
    expect(boxGrowth({ rows: 1, lines: 3, step: 14, originalStep: 14, size: 12, originalSize: 12 })).toBeCloseTo(-28);
  });

  it("accounts for a bigger font", () => {
    expect(boxGrowth({ rows: 1, lines: 1, step: 20, originalStep: 14, size: 18, originalSize: 12 })).toBeGreaterThan(5);
  });
});

describe("pushConflicts", () => {
  it("finds kept items that moved content would land on", () => {
    const moving = [item("rule", [72, 150, 540, 151])];
    const kept = [item("image", [320, 160, 400, 220]), item("far", [72, 400, 100, 410])];
    expect(pushConflicts(moving, kept, 20)).toEqual(["image"]);
    expect(pushConflicts(moving, kept, 0)).toEqual([]);
  });
});
