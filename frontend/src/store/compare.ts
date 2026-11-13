import { create } from "zustand";
import { compareApi } from "../api/compare";
import type { CompareReport, CompareSession, CompareSettings } from "../api/compareTypes";
import type { Job } from "../api/types";
import { ALL_FILTERS, clampZoom, stepChange, visibleChanges, type FilterKey, type Filters } from "../lib/compare";
import { errorMessage, useEditor } from "./editor";

/** closed: editing. setup: choosing the file and options. running: waiting for the result. ready: showing it. */
export type ComparePhase = "closed" | "setup" | "running" | "ready";

export const DEFAULT_SETTINGS: CompareSettings = { mode: "both", dpi: 72, sensitivity: "medium", ignoreCase: false };

const POLL_MS = 400;

interface CompareState {
  phase: ComparePhase;
  docId: string | null;
  session: CompareSession | null;
  report: CompareReport | null;
  settings: CompareSettings;
  uploading: boolean;
  needsPassword: boolean; // the chosen file is protected: ask for its password
  progress: { done: number; total: number; message: string } | null;
  error: string | null;
  filters: Filters;
  activeId: string | null;
  jump: { id: string; nonce: number } | null; // asks the page area to scroll to a change
  zoom: number;
  fit: boolean;
}

interface CompareActions {
  open: () => void;
  close: () => Promise<void>;
  chooseFile: (file: File, password?: string) => Promise<boolean>;
  patchSettings: (patch: Partial<CompareSettings>) => void;
  run: () => Promise<void>;
  backToSetup: () => void;
  toggleFilter: (key: FilterKey) => void;
  goTo: (id: string) => void;
  step: (direction: 1 | -1) => void;
  setZoom: (zoom: number, fit?: boolean) => void;
}

const INITIAL: CompareState = {
  phase: "closed",
  docId: null,
  session: null,
  report: null,
  settings: DEFAULT_SETTINGS,
  uploading: false,
  needsPassword: false,
  progress: null,
  error: null,
  filters: ALL_FILTERS,
  activeId: null,
  jump: null,
  zoom: 1,
  fit: true,
};

let runToken = 0; // a newer run or closing the view cancels the polling of an older one
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export const useCompare = create<CompareState & CompareActions>((set, get) => {
  /** Keeps asking the server until the job ends; gives up quietly when the view was closed meanwhile. */
  async function waitFor(job: Job, token: number): Promise<Job | null> {
    let current = job;
    while (current.status === "running") {
      set({ progress: { done: current.done, total: current.total, message: current.message } });
      await sleep(POLL_MS);
      if (token !== runToken) return null;
      current = await compareApi.job(current.id);
    }
    return token === runToken ? current : null;
  }

  return {
    ...INITIAL,

    open: () => {
      const doc = useEditor.getState().doc;
      if (!doc || get().phase !== "closed") return;
      set({ ...INITIAL, phase: "setup", docId: doc.id });
    },

    close: async () => {
      const { docId, session } = get();
      runToken += 1;
      set({ ...INITIAL });
      if (docId && session) {
        try {
          await compareApi.close(docId, session.id);
        } catch {
          /* the server removes unused comparison files by itself */
        }
      }
    },

    chooseFile: async (file, password) => {
      const { docId } = get();
      if (!docId) return false;
      set({ uploading: true, error: null, needsPassword: false });
      try {
        const session = await compareApi.upload(docId, file, password);
        set({ session, report: null, uploading: false, activeId: null });
        return true;
      } catch (error) {
        const protectedFile = (error as { code?: string }).code === "password_required";
        set({ uploading: false, needsPassword: protectedFile, error: protectedFile && !password ? null : errorMessage(error) });
        return false;
      }
    },

    patchSettings: (patch) => set((state) => ({ settings: { ...state.settings, ...patch } })),

    run: async () => {
      const { docId, session, settings } = get();
      if (!docId || !session) return;
      const token = ++runToken;
      set({ phase: "running", error: null, progress: { done: 0, total: 0, message: "Starting…" } });
      try {
        const started = await compareApi.run(docId, session.id, settings);
        const job = await waitFor(started, token);
        if (!job) return;
        if (job.status === "error") throw new Error(job.error || "The comparison failed.");
        const report = await compareApi.report(docId, session.id);
        if (token !== runToken) return;
        const first = visibleChanges(report, get().filters)[0]?.id ?? null;
        set({ phase: "ready", report, progress: null, activeId: first, jump: null, fit: true });
      } catch (error) {
        if (token === runToken) set({ phase: "setup", progress: null, error: errorMessage(error) });
      }
    },

    backToSetup: () => set({ phase: "setup", error: null }),

    toggleFilter: (key) => set((state) => ({ filters: { ...state.filters, [key]: !state.filters[key] } })),

    goTo: (id) => set({ activeId: id, jump: { id, nonce: Date.now() } }),

    step: (direction) => {
      const { report, filters, activeId } = get();
      const next = stepChange(visibleChanges(report, filters), activeId, direction);
      if (next) get().goTo(next.id);
    },

    setZoom: (zoom, fit = false) => set({ zoom: clampZoom(zoom), fit }),
  };
});
