import { useEffect } from "react";
import { api } from "../api/client";
import { redo, undo, quickDownload } from "../components/layout/TopBar";
import { flushEdit } from "../lib/editSession";
import { useEditor, type Tool } from "../store/editor";

const TOOL_KEYS: Record<string, Tool> = { v: "select", t: "editText", a: "addText", h: "highlight", d: "ink", n: "note" };

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

async function deleteSelection(): Promise<void> {
  const { doc, selection, run, select } = useEditor.getState();
  if (!doc || !selection) return;
  select(null);
  if (selection.kind === "annotation") await run(() => api.deleteAnnotation(doc.id, selection.page, selection.xref), "Deleted");
  if (selection.kind === "image") {
    const items = selection.bbox ? [{ kind: "image", bbox: selection.bbox, xref: selection.xref }] : null;
    await run(() => (items ? api.deleteObjects(doc.id, { page: selection.page, items }) : api.deleteImage(doc.id, selection.page, selection.xref)), "Image deleted");
  }
  if (selection.kind === "graphic") {
    await run(() => api.deleteObjects(doc.id, { page: selection.page, items: [{ kind: "drawing", bbox: selection.bbox }] }), "Deleted");
  }
  if (selection.kind === "field") await run(() => api.deleteField(doc.id, selection.page, selection.xref), "Field deleted");
}

export function useShortcuts(): void {
  useEffect(() => {
    let spaceTool: Tool | null = null;

    const onKeyDown = (event: KeyboardEvent) => {
      const state = useEditor.getState();
      if (!state.doc || state.dialog) return;
      const mod = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();

      if (mod && key === "s") {
        event.preventDefault();
        void quickDownload();
        return;
      }
      if (mod && key === "f") {
        event.preventDefault();
        if (state.sidebar !== "search") state.setSidebar("search");
        return;
      }
      if (mod && (key === "=" || key === "+")) {
        event.preventDefault();
        state.setZoom(state.zoom * 1.2);
        return;
      }
      if (mod && key === "-") {
        event.preventDefault();
        state.setZoom(state.zoom / 1.2);
        return;
      }
      if (mod && key === "0") {
        event.preventDefault();
        state.setZoom(state.zoom, "width");
        return;
      }
      if (isTyping(event.target)) return;
      if (mod && key === "z") {
        event.preventDefault();
        void (event.shiftKey ? redo() : undo());
        return;
      }
      if (mod && key === "y") {
        event.preventDefault();
        void redo();
        return;
      }
      if (mod) return;
      if (event.key === "Escape") {
        state.setPlacement(null);
        state.select(null);
        state.setTool("select");
        return;
      }
      if ((event.key === "Delete" || event.key === "Backspace") && state.selection) {
        event.preventDefault();
        void deleteSelection();
        return;
      }
      if (event.key === "PageDown" || event.key === "PageUp") {
        event.preventDefault();
        const next = Math.max(0, Math.min(state.doc.pages.length - 1, state.currentPage + (event.key === "PageDown" ? 1 : -1)));
        state.scrollTo(next);
        return;
      }
      if (event.key === " " && state.tool !== "pan" && !event.repeat) {
        event.preventDefault();
        spaceTool = state.tool;
        state.setTool("pan");
        return;
      }
      if (event.key === "?") {
        state.openDialog("shortcuts");
        return;
      }
      const tool = TOOL_KEYS[key];
      if (tool) {
        void flushEdit().then(() => useEditor.getState().setTool(tool));
      }
    };

    const onKeyUp = (event: KeyboardEvent) => {
      if (event.key === " " && spaceTool) {
        useEditor.getState().setTool(spaceTool);
        spaceTool = null;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);
}
