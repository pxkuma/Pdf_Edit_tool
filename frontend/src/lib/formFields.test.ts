import { describe, expect, it } from "vitest";
import type { FieldProposal, FormField } from "../api/types";
import {
  acceptedProposals,
  choicesToText,
  duplicateChoice,
  isFieldTool,
  moveInOrder,
  newFieldRect,
  parseChoices,
  proposalRequest,
  selectedValues,
  tooSmall,
  toggled,
} from "./formFields";

const proposal = (over: Partial<FieldProposal> = {}): FieldProposal => ({
  id: "p0-0",
  page: 0,
  kind: "text",
  rect: [150, 90, 400, 102],
  name: "Full name",
  label: "Full name",
  confidence: 0.8,
  reason: "label and line",
  multiline: false,
  format: null,
  ...over,
});

describe("field tools", () => {
  it("knows the tools that create fields", () => {
    expect(isFieldTool("fieldRadio")).toBe(true);
    expect(isFieldTool("fieldSignature")).toBe(true);
    expect(isFieldTool("select")).toBe(false);
    expect(isFieldTool("toString")).toBe(false);
  });

  it("sizes a clicked field by kind and keeps a dragged rectangle", () => {
    expect(newFieldRect("checkbox", [0, 0, 0, 0], true, [10, 20])).toEqual([10, 20, 24, 34]);
    expect(newFieldRect("text", [0, 0, 0, 0], true, [10, 20])).toEqual([10, 20, 170, 40]);
    expect(newFieldRect("text", [5, 5, 50, 30], false, [5, 5])).toEqual([5, 5, 50, 30]);
  });

  it("rejects fields that are too small", () => {
    expect(tooSmall([0, 0, 4, 20])).toBe(true);
    expect(tooSmall([0, 0, 14, 14])).toBe(false);
  });
});

describe("option lists", () => {
  it("parses value=label lines and ignores blanks", () => {
    expect(parseChoices("Red\n\n  de = German \nfr=\n=x\r\nblue")).toEqual([
      { value: "Red", label: "Red" },
      { value: "de", label: "German" },
      { value: "fr=", label: "fr=" },
      { value: "=x", label: "=x" },
      { value: "blue", label: "blue" },
    ]);
  });

  it("round-trips through the text form", () => {
    const choices = [{ value: "a", label: "Apple" }, { value: "b", label: "b" }];
    expect(parseChoices(choicesToText(choices))).toEqual(choices);
  });

  it("finds repeated export values", () => {
    expect(duplicateChoice([{ value: "a", label: "A" }, { value: "a", label: "Again" }])).toBe("a");
    expect(duplicateChoice([{ value: "a", label: "A" }])).toBeNull();
  });

  it("reads selected values of a list", () => {
    expect(selectedValues({ value: ["en", "fr"] } as FormField)).toEqual(["en", "fr"]);
    expect(selectedValues({ value: "en" } as FormField)).toEqual(["en"]);
    expect(selectedValues({ value: "" } as FormField)).toEqual([]);
    expect(selectedValues({ value: false } as FormField)).toEqual([]);
  });
});

describe("detected fields", () => {
  it("turns a proposal into a creation request", () => {
    expect(proposalRequest(proposal())).toEqual({
      page: 0,
      kind: "text",
      rect: [150, 90, 400, 102],
      props: { name: "Full name", tooltip: "Full name" },
    });
    const date = proposalRequest(proposal({ format: { kind: "date", pattern: "mm/dd/yyyy" }, multiline: true }));
    expect(date.props).toMatchObject({ multiline: true, format: { kind: "date", decimals: 2, pattern: "mm/dd/yyyy" } });
    expect(proposalRequest(proposal({ kind: "checkbox" })).props?.tooltip).toBeUndefined();
  });

  it("keeps the proposals the user did not reject", () => {
    const all = [proposal({ id: "a" }), proposal({ id: "b" }), proposal({ id: "c" })];
    const rejected = toggled(new Set<string>(), "b");
    expect(acceptedProposals(all, rejected).map((p) => p.id)).toEqual(["a", "c"]);
    expect(toggled(rejected, "b").size).toBe(0);
    expect(rejected.size).toBe(1); // the original set is not changed
  });
});

describe("tab order", () => {
  it("moves one entry without touching the input", () => {
    const ids = [1, 2, 3, 4];
    expect(moveInOrder(ids, 2, -1)).toEqual([1, 3, 2, 4]);
    expect(moveInOrder(ids, 0, 1)).toEqual([2, 1, 3, 4]);
    expect(moveInOrder(ids, 0, -1)).toEqual(ids);
    expect(moveInOrder(ids, 3, 1)).toEqual(ids);
    expect(ids).toEqual([1, 2, 3, 4]);
  });
});
