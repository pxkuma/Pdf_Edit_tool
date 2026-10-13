import { useEffect, useState } from "react";
import { create } from "zustand";
import { api } from "../api/client";
import type { PageModel } from "../api/types";

const cache = new Map<string, Promise<PageModel>>();
const MAX_ENTRIES = 200;

/** Bumped when every page model must be re-read (e.g. after installing a font). */
const useModelGeneration = create<{ generation: number }>(() => ({ generation: 0 }));

export function invalidatePageModels(): void {
  cache.clear();
  useModelGeneration.setState((s) => ({ generation: s.generation + 1 }));
}

function key(docId: string, page: number, token: string): string {
  return `${docId}:${page}:${token}`;
}

export function loadPageModel(docId: string, page: number, token: string): Promise<PageModel> {
  const k = key(docId, page, token);
  let promise = cache.get(k);
  if (!promise) {
    promise = api.pageModel(docId, page);
    promise.catch(() => cache.delete(k));
    cache.set(k, promise);
    if (cache.size > MAX_ENTRIES) {
      const oldest = cache.keys().next().value;
      if (oldest) cache.delete(oldest);
    }
  }
  return promise;
}

/** Page model (text runs, annotations, images, fields) for a page revision. */
export function usePageModel(docId: string, page: number, token: string, enabled: boolean): PageModel | null {
  const [state, setState] = useState<{ token: string; model: PageModel } | null>(null);
  const generation = useModelGeneration((s) => s.generation);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    loadPageModel(docId, page, token)
      .then((model) => alive && setState({ token, model }))
      .catch(() => alive && setState(null));
    return () => {
      alive = false;
    };
  }, [docId, page, token, enabled, generation]);
  return state && state.token === token ? state.model : null;
}
