import { describe, expect, it } from "vitest";
import { removedNote } from "./redaction";

describe("removedNote", () => {
  it("is empty when nothing else was removed", () => {
    expect(removedNote({ annotations: 0, fields: 0, links: 0 })).toBe("");
    expect(removedNote(undefined)).toBe("");
  });

  it("names a single kind of object", () => {
    expect(removedNote({ annotations: 1, fields: 0, links: 0 })).toBe(" (also removed 1 comment)");
    expect(removedNote({ annotations: 0, fields: 3, links: 0 })).toBe(" (also removed 3 form fields)");
  });

  it("lists several kinds in plain English", () => {
    expect(removedNote({ annotations: 2, fields: 1, links: 0 })).toBe(" (also removed 2 comments and 1 form field)");
    expect(removedNote({ annotations: 2, fields: 1, links: 4 })).toBe(" (also removed 2 comments, 1 form field and 4 links)");
  });
});
