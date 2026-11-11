import { describe, expect, it } from "vitest";
import { missingCharsWarning } from "./missingChars";

describe("missingCharsWarning", () => {
  it("is empty when every character could be drawn", () => {
    expect(missingCharsWarning([])).toBeNull();
    expect(missingCharsWarning(undefined)).toBeNull();
  });

  it("names the characters that were skipped", () => {
    expect(missingCharsWarning([""])).toBe("No installed font contains:  — those characters were skipped.");
    expect(missingCharsWarning(["Ω", "€"])).toBe("No installed font contains: Ω € — those characters were skipped.");
  });
});
