import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CompareChange, CompareReport, CompareSession } from "../api/compareTypes";
import type { DocInfo, Job } from "../api/types";

const upload = vi.fn();
const run = vi.fn();
const job = vi.fn();
const report = vi.fn();
const close = vi.fn();
vi.mock("../api/client", () => ({ ApiError: class extends Error {}, api: {} }));
vi.mock("../api/compare", () => ({
  compareApi: {
    upload: (...args: unknown[]) => upload(...args),
    run: (...args: unknown[]) => run(...args),
    job: (...args: unknown[]) => job(...args),
    report: (...args: unknown[]) => report(...args),
    close: (...args: unknown[]) => close(...args),
  },
}));

import { useEditor } from "./editor";
import { DEFAULT_SETTINGS, useCompare } from "./compare";

const session: CompareSession = { id: "s1", docId: "d1", filename: "new.pdf", created: 0, pageCount: 2, pages: [], hasReport: false };

function change(id: string, kind: CompareChange["kind"], pair: number): CompareChange {
  return {
    id, kind, type: kind === "visual" ? "region" : "insert", pair, pageA: pair, pageB: pair, oldText: "", newText: id,
    before: "", after: "", rectsA: [], rectsB: [], anchorA: null, anchorB: null,
  };
}

function reportWith(...changes: CompareChange[]): CompareReport {
  const pairs = [0, 1].map((index) => ({
    index, pageA: index, pageB: index, status: "changed" as const, similarity: 1, sizeA: [600, 800] as [number, number],
    sizeB: [600, 800] as [number, number], sizeChanged: false, text: null, visual: null,
    changes: changes.filter((c) => c.pair === index),
  }));
  return {
    options: DEFAULT_SETTINGS, pairs, baseVersion: "v0", base: { filename: "a.pdf", pages: 2 }, other: { filename: "new.pdf", pages: 2 },
    totals: {} as CompareReport["totals"],
  };
}

function jobState(status: Job["status"], extra: Partial<Job> = {}): Job {
  return { id: "j1", docId: "d1", kind: "compare", total: 4, done: 0, status, message: "", error: "", result: null, document: null, ...extra };
}

const openDoc = { id: "d1", filename: "a.pdf", pages: [], version: "v0" } as unknown as DocInfo;

beforeEach(() => {
  vi.useFakeTimers();
  for (const fn of [upload, run, job, report, close]) fn.mockReset();
  close.mockResolvedValue(null);
  useEditor.setState({ doc: openDoc });
  void useCompare.getState().close();
});

afterEach(() => vi.useRealTimers());

async function ready(...changes: CompareChange[]) {
  upload.mockResolvedValue(session);
  run.mockResolvedValue(jobState("running"));
  job.mockResolvedValue(jobState("done", { done: 4 }));
  report.mockResolvedValue(reportWith(...changes));
  useCompare.getState().open();
  await useCompare.getState().chooseFile(new File(["x"], "new.pdf"));
  const finished = useCompare.getState().run();
  await vi.advanceTimersByTimeAsync(1000);
  await finished;
}

describe("opening and closing the compare view", () => {
  it("starts at the setup screen for the open document", () => {
    expect(useCompare.getState().phase).toBe("closed");
    useCompare.getState().open();
    expect(useCompare.getState()).toMatchObject({ phase: "setup", docId: "d1", report: null });
  });

  it("does not open without a document", () => {
    useEditor.setState({ doc: null });
    useCompare.getState().open();
    expect(useCompare.getState().phase).toBe("closed");
  });

  it("returns to editing and removes the second file from the server", async () => {
    await ready(change("c0", "text", 0));
    await useCompare.getState().close();
    expect(useCompare.getState()).toMatchObject({ phase: "closed", session: null, report: null });
    expect(close).toHaveBeenCalledWith("d1", "s1");
  });

  it("still closes when the server cannot be reached", async () => {
    await ready();
    close.mockRejectedValue(new Error("offline"));
    await useCompare.getState().close();
    expect(useCompare.getState().phase).toBe("closed");
  });
});

describe("choosing the file", () => {
  it("keeps the session the server created", async () => {
    upload.mockResolvedValue(session);
    useCompare.getState().open();
    expect(await useCompare.getState().chooseFile(new File(["x"], "new.pdf"))).toBe(true);
    expect(useCompare.getState().session).toEqual(session);
    expect(upload).toHaveBeenCalledWith("d1", expect.any(File), undefined);
  });

  it("asks for the password of a protected file, then sends it", async () => {
    upload.mockRejectedValueOnce(Object.assign(new Error("This PDF is password protected."), { code: "password_required" }));
    useCompare.getState().open();
    const file = new File(["x"], "locked.pdf");
    expect(await useCompare.getState().chooseFile(file)).toBe(false);
    expect(useCompare.getState()).toMatchObject({ needsPassword: true, error: null });
    upload.mockResolvedValueOnce(session);
    expect(await useCompare.getState().chooseFile(file, "secret")).toBe(true);
    expect(upload).toHaveBeenLastCalledWith("d1", file, "secret");
    expect(useCompare.getState().needsPassword).toBe(false);
  });

  it("shows why a file was refused", async () => {
    upload.mockRejectedValue(new Error("The file is larger than 200 MB."));
    useCompare.getState().open();
    expect(await useCompare.getState().chooseFile(new File(["x"], "big.pdf"))).toBe(false);
    expect(useCompare.getState()).toMatchObject({ error: "The file is larger than 200 MB.", session: null, uploading: false });
  });
});

describe("running the comparison", () => {
  it("shows progress while the server works, then the report with the first change selected", async () => {
    await ready(change("c0", "text", 0), change("c1", "visual", 1));
    const state = useCompare.getState();
    expect(state.phase).toBe("ready");
    expect(state.report?.pairs).toHaveLength(2);
    expect(state.activeId).toBe("c0");
    expect(run).toHaveBeenCalledWith("d1", "s1", DEFAULT_SETTINGS);
  });

  it("goes back to the setup screen with the reason when the job fails", async () => {
    upload.mockResolvedValue(session);
    run.mockResolvedValue(jobState("running"));
    job.mockResolvedValue(jobState("error", { error: "A visual comparison covers at most 300 pages." }));
    useCompare.getState().open();
    await useCompare.getState().chooseFile(new File(["x"], "n.pdf"));
    const finished = useCompare.getState().run();
    await vi.advanceTimersByTimeAsync(1000);
    await finished;
    expect(useCompare.getState()).toMatchObject({ phase: "setup", error: "A visual comparison covers at most 300 pages." });
  });

  it("stops quietly when the view is closed while the job is running", async () => {
    upload.mockResolvedValue(session);
    run.mockResolvedValue(jobState("running"));
    job.mockResolvedValue(jobState("running"));
    useCompare.getState().open();
    await useCompare.getState().chooseFile(new File(["x"], "n.pdf"));
    const finished = useCompare.getState().run();
    await vi.advanceTimersByTimeAsync(500);
    await useCompare.getState().close();
    await vi.advanceTimersByTimeAsync(2000);
    await finished;
    expect(useCompare.getState().phase).toBe("closed");
    expect(report).not.toHaveBeenCalled();
  });

  it("uses the chosen options", async () => {
    upload.mockResolvedValue(session);
    run.mockResolvedValue(jobState("done"));
    report.mockResolvedValue(reportWith());
    useCompare.getState().open();
    useCompare.getState().patchSettings({ mode: "text", ignoreCase: true });
    await useCompare.getState().chooseFile(new File(["x"], "n.pdf"));
    await useCompare.getState().run();
    expect(run).toHaveBeenCalledWith("d1", "s1", { ...DEFAULT_SETTINGS, mode: "text", ignoreCase: true });
  });

  it("can go back to change the options without choosing the file again", async () => {
    await ready(change("c0", "text", 0));
    useCompare.getState().backToSetup();
    expect(useCompare.getState()).toMatchObject({ phase: "setup", session });
  });
});

describe("moving between changes", () => {
  it("steps through the visible changes and asks the page area to scroll", async () => {
    await ready(change("c0", "text", 0), change("c1", "visual", 0), change("c2", "text", 1));
    useCompare.getState().step(1);
    expect(useCompare.getState().activeId).toBe("c1");
    expect(useCompare.getState().jump?.id).toBe("c1");
    useCompare.getState().step(-1);
    useCompare.getState().step(-1);
    expect(useCompare.getState().activeId).toBe("c2");
  });

  it("skips the types that are switched off", async () => {
    await ready(change("c0", "text", 0), change("c1", "visual", 0), change("c2", "text", 1));
    useCompare.getState().toggleFilter("image");
    expect(useCompare.getState().filters).toEqual({ text: true, image: false, page: true });
    useCompare.getState().step(1);
    expect(useCompare.getState().activeId).toBe("c2");
  });

  it("does nothing without changes", async () => {
    await ready();
    useCompare.getState().step(1);
    expect(useCompare.getState().activeId).toBeNull();
  });
});

describe("zoom", () => {
  it("is limited, and a manual zoom turns off fit-to-width", () => {
    useCompare.getState().setZoom(50);
    expect(useCompare.getState()).toMatchObject({ zoom: 4, fit: false });
    useCompare.getState().setZoom(0.01, true);
    expect(useCompare.getState()).toMatchObject({ zoom: 0.2, fit: true });
  });
});
