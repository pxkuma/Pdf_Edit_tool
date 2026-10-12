import { create } from "zustand";
import { api } from "../api/client";
import type { FontFaceInfo, FontFamily } from "../api/types";

interface FontState {
  families: FontFamily[];
  defaultFace: string | null;
  loaded: boolean;
  load: (force?: boolean) => Promise<void>;
}

export const useFonts = create<FontState>((set, get) => ({
  families: [],
  defaultFace: null,
  loaded: false,
  load: async (force = false) => {
    if (get().loaded && !force) return;
    const data = await api.fonts();
    set({ families: data.families, defaultFace: data.default, loaded: true });
  },
}));

export function findFace(families: FontFamily[], faceId: string | null): { family: FontFamily; face: FontFaceInfo } | null {
  if (!faceId) return null;
  for (const family of families) {
    const face = family.faces.find((f) => f.id === faceId);
    if (face) return { family, face };
  }
  return null;
}

export function variantOf(family: FontFamily, bold: boolean, italic: boolean): FontFaceInfo {
  const score = (f: FontFaceInfo) =>
    (f.bold === bold ? 2 : 0) + (f.italic === italic ? 2 : 0) + (/^(regular|bold|italic|bold italic)$/i.test(f.style) ? 1 : 0);
  return [...family.faces].sort((a, b) => score(b) - score(a))[0];
}

const loading = new Map<string, Promise<string>>();

/** Load an installed font into the browser so editors preview the real typeface. */
export function ensureFace(faceId: string | null | undefined): Promise<string> {
  if (!faceId) return Promise.resolve("sans-serif");
  const family = `pdfs-${faceId}`;
  const existing = loading.get(faceId);
  if (existing) return existing;
  const promise = (async () => {
    try {
      const face = new FontFace(family, `url(${api.fontFileUrl(faceId)})`);
      await face.load();
      document.fonts.add(face);
      return `"${family}"`;
    } catch {
      return "sans-serif";
    }
  })();
  loading.set(faceId, promise);
  return promise;
}

export function cssFamily(faceId: string | null | undefined, fallback: { serif?: boolean; mono?: boolean } = {}): string {
  const generic = fallback.mono ? "monospace" : fallback.serif ? "serif" : "sans-serif";
  return faceId ? `"pdfs-${faceId}", ${generic}` : generic;
}
