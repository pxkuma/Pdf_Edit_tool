import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocInfo, MutationResponse } from "../api/types";

const calls: string[] = [];
const undo = vi.fn();
vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: { undo: (...args: unknown[]) => undo(...args), redo: vi.fn(), jump: vi.fn() },
}));

import { useEditor } from "./editor";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function docAt(cursor: number, canUndo = cursor > 0): DocInfo {
  return { id: "d", filename: "a.pdf", title: "", pages: [], version: `v${cursor}`, canUndo, canRedo: false, cursor, history: [], wasEncrypted: false, hasForms: false, signatures: 0 };
}

function response(cursor: number): MutationResponse<null> {
  return { document: docAt(cursor), result: null };
}

beforeEach(() => {
  vi.stubGlobal("window", globalThis); // toasts schedule their own removal with window.setTimeout
  calls.length = 0;
  undo.mockReset();
  useEditor.setState({ doc: docAt(0), tool: "select", selection: null, activeEdit: null, heldTool: null, busy: 0, toasts: [] });
});

afterEach(() => vi.unstubAllGlobals());

describe("holding a tool temporarily (Space to pan)", () => {
  it("keeps the selection and the open editor, and gives the old tool back", () => {
    const selection = { kind: "image", page: 0, xref: 5, bbox: [0, 0, 10, 10] } as never;
    useEditor.setState({ tool: "select", selection });
    useEditor.getState().holdTool("pan");
    expect(useEditor.getState().tool).toBe("pan");
    expect(useEditor.getState().selection).toBe(selection);
    useEditor.getState().releaseTool();
    expect(useEditor.getState().tool).toBe("select");
    expect(useEditor.getState().selection).toBe(selection);
  });

  it("ignores a second hold and a release without a hold", () => {
    useEditor.getState().releaseTool();
    expect(useEditor.getState().tool).toBe("select");
    useEditor.getState().holdTool("pan");
    useEditor.getState().holdTool("pan");
    useEditor.getState().releaseTool();
    expect(useEditor.getState().tool).toBe("select");
  });
});

describe("overlapping actions", () => {
  it("run one after the other so the document never moves backwards", async () => {
    const slow = useEditor.getState().run(async () => {
      calls.push("start 1");
      await sleep(25);
      calls.push("end 1");
      return response(1);
    });
    const fast = useEditor.getState().run(async () => {
      calls.push("start 2");
      calls.push("end 2");
      return response(2);
    });
    await Promise.all([slow, fast]);
    expect(calls).toEqual(["start 1", "end 1", "start 2", "end 2"]);
    expect(useEditor.getState().doc?.cursor).toBe(2);
    expect(useEditor.getState().busy).toBe(0);
  });

  it("let a failing action report its error and not block the next one", async () => {
    const failed = await useEditor.getState().run(async () => {
      throw new Error("nope");
    });
    expect(failed).toBeUndefined();
    expect(useEditor.getState().toasts.at(-1)?.message).toBe("nope");
    await useEditor.getState().run(async () => response(3));
    expect(useEditor.getState().doc?.cursor).toBe(3);
  });

  it("undo waits for a running action and uses the document it produced", async () => {
    undo.mockImplementation(async () => docAt(0));
    const mutation = useEditor.getState().run(async () => {
      await sleep(20);
      return response(1);
    });
    const stepBack = useEditor.getState().moveInHistory("undo"); // asked while doc.canUndo is still false
    await Promise.all([mutation, stepBack]);
    expect(undo).toHaveBeenCalledTimes(1);
    expect(useEditor.getState().doc?.cursor).toBe(0);
  });

  it("undo does nothing when there is nothing to undo", async () => {
    await useEditor.getState().moveInHistory("undo");
    expect(undo).not.toHaveBeenCalled();
  });
});
