import { describe, expect, it } from "vitest";
import { serialized } from "./serialQueue";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("serialized", () => {
  it("runs work one call at a time, in the order it was requested", async () => {
    const log: string[] = [];
    const task = (name: string, ms: number) => async () => {
      log.push(`start ${name}`);
      await sleep(ms);
      log.push(`end ${name}`);
      return name;
    };
    const results = await Promise.all([serialized(task("a", 20)), serialized(task("b", 1)), serialized(task("c", 5))]);
    expect(results).toEqual(["a", "b", "c"]);
    expect(log).toEqual(["start a", "end a", "start b", "end b", "start c", "end c"]);
  });

  it("passes a failure to its own caller without stopping the queue", async () => {
    const failing = serialized(async () => {
      throw new Error("boom");
    });
    const next = serialized(async () => "still runs");
    await expect(failing).rejects.toThrow("boom");
    await expect(next).resolves.toBe("still runs");
  });

  it("also survives work that throws before returning a promise", async () => {
    const failing = serialized((() => {
      throw new Error("sync boom");
    }) as () => Promise<never>);
    await expect(failing).rejects.toThrow("sync boom");
    await expect(serialized(async () => 1)).resolves.toBe(1);
  });
});
