import { request } from "./client";
import type { CompareReport, CompareSession, CompareSettings } from "./compareTypes";
import type { Job } from "./types";

const base = (docId: string) => `/api/documents/${docId}/compare`;

/** Document comparison endpoints. Nothing here changes the open document. */
export const compareApi = {
  /** Upload the file to compare with. The previous file of this document is replaced. */
  upload(docId: string, file: File, password?: string): Promise<CompareSession> {
    const form = new FormData();
    form.append("file", file);
    if (password) form.append("password", password);
    return request("POST", base(docId), form);
  },
  run: (docId: string, sessionId: string, settings: CompareSettings) =>
    request<Job>("POST", `${base(docId)}/${sessionId}/run`, {
      mode: settings.mode,
      dpi: settings.dpi,
      sensitivity: settings.sensitivity,
      ignore_case: settings.ignoreCase,
    }),
  job: (jobId: string) => request<Job>("GET", `/api/jobs/${jobId}`),
  report: (docId: string, sessionId: string) => request<CompareReport>("GET", `${base(docId)}/${sessionId}/report`),
  close: (docId: string, sessionId: string) => request<null>("DELETE", `${base(docId)}/${sessionId}`),
  /** A page of the second file as an image. */
  renderUrl: (docId: string, sessionId: string, page: number, scale: number) =>
    `${base(docId)}/${sessionId}/pages/${page}/render?scale=${scale}`,
};
