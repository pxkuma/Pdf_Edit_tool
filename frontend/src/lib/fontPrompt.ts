/**
 * Offer to download the exact font a PDF uses when it is not installed.
 *
 * Starting to edit text whose font is missing opens a prompt (once per font):
 * free fonts can be downloaded so edits continue in that very font; commercial
 * ones can be uploaded. Answers are remembered per font name.
 */
import { create } from "zustand";
import { api } from "../api/client";
import type { FontLookup, Span } from "../api/types";
import { errorMessage, useEditor } from "../store/editor";
import { useFonts } from "./fonts";
import { invalidatePageModels } from "./pageModel";

const NEVER_KEY = "pdfstudio.fontPrompt.never";

const normalize = (name: string) => name.toLowerCase().replace(/[^a-z0-9]/g, "");

interface FontPromptState {
  lookup: FontLookup | null;
  busy: boolean;
  /** Fonts answered with "not now" in this session. */
  skipped: string[];
  open: (lookup: FontLookup) => void;
  close: (remember: "session" | "never") => void;
  setBusy: (busy: boolean) => void;
}

function readNever(): string[] {
  try {
    const raw = localStorage.getItem(NEVER_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function writeNever(names: string[]): void {
  try {
    localStorage.setItem(NEVER_KEY, JSON.stringify(names.slice(-200)));
  } catch {
    /* storage unavailable: the prompt may simply come back */
  }
}

export const useFontPrompt = create<FontPromptState>((set, get) => ({
  lookup: null,
  busy: false,
  skipped: [],
  open: (lookup) => set({ lookup }),
  close: (remember) => {
    const name = get().lookup?.name;
    if (name && remember === "never") writeNever([...readNever(), name]);
    set((s) => ({ lookup: null, busy: false, skipped: name ? [...s.skipped, name] : s.skipped }));
  },
  setBusy: (busy) => set({ busy }),
}));

const lookups = new Map<string, Promise<FontLookup>>();

function lookupFont(name: string): Promise<FontLookup> {
  let promise = lookups.get(name);
  if (!promise) {
    promise = api.fontLookup(name);
    promise.catch(() => lookups.delete(name));
    lookups.set(name, promise);
  }
  return promise;
}

/** Called when editing starts: prompt if the span's own font is not installed. */
export async function checkSpanFont(span: Span): Promise<void> {
  if (span.ocr || span.installed !== false || !span.font) return;
  const state = useFontPrompt.getState();
  if (state.lookup || state.skipped.includes(span.font) || readNever().includes(span.font)) return;
  try {
    const result = await lookupFont(span.font);
    if (result.status !== "installed" && !useFontPrompt.getState().lookup) state.open(result);
  } catch {
    /* lookup failures never block editing */
  }
}

/** Ask about a specific document font (from the Fonts panel). */
export async function promptForFont(name: string): Promise<void> {
  lookups.delete(name);
  try {
    useFontPrompt.getState().open(await lookupFont(name));
  } catch (error) {
    useEditor.getState().toast(errorMessage(error), "error");
  }
}

/** After a font was installed: refresh pickers, page models and the open editor's preview. */
async function afterInstall(faceId: string, family: string, pdfName: string): Promise<void> {
  lookups.clear();
  await useFonts.getState().load(true);
  invalidatePageModels();
  const { activeEdit, setActiveEdit, toast } = useEditor.getState();
  if (activeEdit && activeEdit.span.font === pdfName) {
    setActiveEdit({ ...activeEdit, span: { ...activeEdit.span, face: faceId, installed: true } });
  }
  toast(`${family} is installed. Your edits now use this font.`, "success");
}

export async function downloadPromptedFont(): Promise<void> {
  const { lookup, setBusy, close } = useFontPrompt.getState();
  if (!lookup) return;
  setBusy(true);
  try {
    const result = await api.downloadFont(lookup.name);
    close("session");
    await afterInstall(result.face, result.family, lookup.name);
  } catch (error) {
    setBusy(false);
    useEditor.getState().toast(errorMessage(error), "error");
  }
}

export async function uploadPromptedFont(file: File): Promise<void> {
  const { lookup, setBusy, close } = useFontPrompt.getState();
  if (!lookup) return;
  setBusy(true);
  try {
    const face = await api.uploadFont(file);
    close("session");
    const same = normalize(face.family) === normalize(lookup.family);
    await afterInstall(face.id, face.family, lookup.name);
    if (!same) {
      // A differently named font: use it explicitly for the text being edited.
      const { activeEdit, patchDraft, toast } = useEditor.getState();
      if (activeEdit && activeEdit.span.font === lookup.name) patchDraft({ font: `face:${face.id}` });
      toast(`“${face.family}” doesn't have the PDF's font name (${lookup.family}), so it is selected for this text only.`, "info");
    }
  } catch (error) {
    setBusy(false);
    useEditor.getState().toast(errorMessage(error), "error");
  }
}
