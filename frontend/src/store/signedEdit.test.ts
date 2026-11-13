import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocInfo, MutationResponse } from "../api/types";

vi.mock("../api/client", () => ({ ApiError: class extends Error {}, api: {} }));

import { useEditor } from "./editor";

function signedDoc(signatures: number): DocInfo {
  return { id: "d", filename: "a.pdf", title: "", pages: [], version: "v1", canUndo: false, canRedo: false, cursor: 0, history: [], wasEncrypted: false, hasForms: false, signatures };
}

const ok = (): Promise<MutationResponse<string>> => Promise.resolve({ document: signedDoc(1), result: "done" });

beforeEach(() => {
  vi.stubGlobal("window", globalThis);
  useEditor.setState({ doc: signedDoc(1), signedEditConsent: null, signedEditPrompt: false, busy: 0, toasts: [] });
});

afterEach(() => vi.unstubAllGlobals());

describe("editing a signed document", () => {
  it("asks first and does nothing when the user keeps it unchanged", async () => {
    const fn = vi.fn(ok);
    const pending = useEditor.getState().run(fn);
    await Promise.resolve();
    expect(useEditor.getState().signedEditPrompt).toBe(true);
    useEditor.getState().answerSignedEdit(false);
    expect(await pending).toBeUndefined();
    expect(fn).not.toHaveBeenCalled();
    expect(useEditor.getState().signedEditPrompt).toBe(false);
  });

  it("runs the edit after confirmation and does not ask again", async () => {
    const pending = useEditor.getState().run(ok);
    await Promise.resolve();
    useEditor.getState().answerSignedEdit(true);
    expect(await pending).toBe("done");
    const second = vi.fn(ok);
    expect(await useEditor.getState().run(second)).toBe("done");
    expect(second).toHaveBeenCalledOnce();
  });

  it("asks once for edits that are waiting together", async () => {
    const a = useEditor.getState().confirmSignedEdit();
    const b = useEditor.getState().confirmSignedEdit();
    useEditor.getState().answerSignedEdit(true);
    expect(await Promise.all([a, b])).toEqual([true, true]);
  });

  it("asks again after another signature was added", async () => {
    useEditor.getState().answerSignedEdit(true);
    useEditor.setState({ signedEditConsent: "d:1", doc: signedDoc(2) });
    const pending = useEditor.getState().confirmSignedEdit();
    expect(useEditor.getState().signedEditPrompt).toBe(true);
    useEditor.getState().answerSignedEdit(false);
    expect(await pending).toBe(false);
  });

  it("lets signing and reverting through without asking", async () => {
    const fn = vi.fn(ok);
    expect(await useEditor.getState().run(fn, undefined, { allowSigned: true })).toBe("done");
    expect(useEditor.getState().signedEditPrompt).toBe(false);
  });

  it("never asks for unsigned documents", async () => {
    useEditor.setState({ doc: signedDoc(0) });
    expect(await useEditor.getState().confirmSignedEdit()).toBe(true);
  });
});
