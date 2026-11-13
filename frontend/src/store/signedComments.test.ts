import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocInfo, MutationResponse } from "../api/types";
import panelSource from "../components/sidebar/CommentsPanel.tsx?raw";

const MUTATIONS = ["addComment", "editComment", "deleteComment", "replyToComment", "setCommentStatus", "importXfdf"] as const;

vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: Object.fromEntries(["addComment", "editComment", "deleteComment", "replyToComment", "setCommentStatus", "importXfdf"].map((name) => [name, vi.fn()])),
}));

import { api } from "../api/client";
import { useEditor } from "./editor";

function signedDoc(signatures: number): DocInfo {
  return { id: "d", filename: "a.pdf", title: "", pages: [], version: "v1", canUndo: false, canRedo: false, cursor: 0, history: [], wasEncrypted: false, hasForms: false, signatures };
}

const answer = (): Promise<MutationResponse<unknown>> => Promise.resolve({ document: signedDoc(1), result: { xref: 1 } });

beforeEach(() => {
  vi.stubGlobal("window", globalThis);
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined });
  for (const name of MUTATIONS) vi.mocked(api[name]).mockReset().mockImplementation(answer as never);
  useEditor.setState({ doc: signedDoc(1), signedEditConsent: null, signedEditPrompt: false, busy: 0, toasts: [] });
});

afterEach(() => vi.unstubAllGlobals());

describe("comments on a signed document", () => {
  it.each(MUTATIONS)("%s waits for the signed-edit question and stops when it is declined", async (name) => {
    const call = vi.mocked(api[name]);
    const pending = useEditor.getState().run(() => (call as unknown as () => Promise<MutationResponse<unknown>>)());
    await Promise.resolve();
    expect(useEditor.getState().signedEditPrompt).toBe(true);
    expect(call).not.toHaveBeenCalled();
    useEditor.getState().answerSignedEdit(false);
    expect(await pending).toBeUndefined();
    expect(call).not.toHaveBeenCalled();
  });

  it.each(MUTATIONS)("%s goes ahead once the user agreed to edit", async (name) => {
    const call = vi.mocked(api[name]);
    const pending = useEditor.getState().run(() => (call as unknown as () => Promise<MutationResponse<unknown>>)());
    await Promise.resolve();
    useEditor.getState().answerSignedEdit(true);
    await pending;
    expect(call).toHaveBeenCalledOnce();
  });

  it("is wired that way: the panel sends every comment change through the guarded run()", () => {
    for (const name of MUTATIONS) {
      const calls = panelSource.match(new RegExp(`api\\.${name}\\(`, "g")) ?? [];
      const guarded = panelSource.match(new RegExp(`\\brun\\(\\(\\) => api\\.${name}\\(`, "g")) ?? [];
      expect(calls.length, `${name} is used by the panel`).toBeGreaterThan(0);
      expect(guarded.length, `${name} must only be called inside run()`).toBe(calls.length);
    }
    expect(panelSource).not.toMatch(/allowSigned/);
  });
});
