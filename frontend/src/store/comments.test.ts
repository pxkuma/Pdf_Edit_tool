import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocInfo } from "../api/types";

vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: { undo: vi.fn(), redo: vi.fn(), jump: vi.fn() },
}));

import { useEditor } from "./editor";

function docNamed(id: string): DocInfo {
  return { id, filename: "a.pdf", title: "", pages: [], version: "v1", canUndo: false, canRedo: false, cursor: 0, history: [], wasEncrypted: false, hasForms: false, signatures: 0 };
}

let storage: Record<string, string> = {};

beforeEach(() => {
  storage = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage[key] ?? null,
    setItem: (key: string, value: string) => {
      storage[key] = value;
    },
  });
  useEditor.setState({ doc: docNamed("one"), activeComment: null, scrollRequest: null, commentAuthor: "", sidebar: "thumbnails" });
});

afterEach(() => vi.unstubAllGlobals());

describe("pointing at a comment", () => {
  it("remembers the comment and scrolls to its place on the page", () => {
    useEditor.getState().focusComment(3, 42, 120);
    const state = useEditor.getState();
    expect(state.activeComment).toMatchObject({ page: 3, xref: 42 });
    expect(state.scrollRequest).toMatchObject({ page: 3, y: 120 });
  });

  it("flashes again when the same comment is chosen twice", async () => {
    useEditor.getState().focusComment(0, 7, 10);
    const first = useEditor.getState().activeComment?.nonce;
    await new Promise((resolve) => setTimeout(resolve, 2));
    useEditor.getState().focusComment(0, 7, 10);
    expect(useEditor.getState().activeComment?.nonce).not.toBe(first);
  });

  it("is cleared on demand and when another document opens, but not by an edit of the same one", () => {
    useEditor.getState().focusComment(0, 7, 10);
    useEditor.getState().setDoc({ ...docNamed("one"), version: "v2" });
    expect(useEditor.getState().activeComment).not.toBeNull();
    useEditor.getState().setDoc(docNamed("two"));
    expect(useEditor.getState().activeComment).toBeNull();
    useEditor.getState().focusComment(0, 7, 10);
    useEditor.getState().clearActiveComment();
    expect(useEditor.getState().activeComment).toBeNull();
  });
});

describe("the commenter's name", () => {
  it("is remembered, and cut to a sensible length", () => {
    useEditor.getState().setCommentAuthor("Erin");
    expect(useEditor.getState().commentAuthor).toBe("Erin");
    expect(storage["pdfstudio.commentAuthor"]).toBe("Erin");
    useEditor.getState().setCommentAuthor("x".repeat(500));
    expect(useEditor.getState().commentAuthor).toHaveLength(200);
  });

  it("still works when the browser refuses to store it", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    useEditor.getState().setCommentAuthor("Fay");
    expect(useEditor.getState().commentAuthor).toBe("Fay");
  });
});

describe("the Comments panel", () => {
  it("opens from the sidebar like the other panels and toggles shut", () => {
    useEditor.getState().setSidebar("comments");
    expect(useEditor.getState().sidebar).toBe("comments");
    useEditor.getState().setSidebar("comments");
    expect(useEditor.getState().sidebar).toBeNull();
  });
});
