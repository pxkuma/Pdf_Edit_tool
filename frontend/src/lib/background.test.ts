import { describe, expect, it } from "vitest";
import { dominantColor } from "./background";

function pixels(colors: [number, number, number][]): Uint8ClampedArray {
  return new Uint8ClampedArray(colors.flatMap(([r, g, b]) => [r, g, b, 255]));
}

describe("dominantColor", () => {
  it("returns the most common colour, ignoring a few text pixels", () => {
    const data = pixels([...Array(20).fill([221, 230, 255]), [0, 0, 0], [10, 10, 10], [222, 231, 254]]);
    expect(dominantColor(data)).toBe("rgb(221, 230, 255)");
  });

  it("falls back to white when there is nothing to sample", () => {
    expect(dominantColor(new Uint8ClampedArray())).toBe("#ffffff");
  });
});
