import { FileText, FileUp, Loader2, Lock, X } from "lucide-react";
import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { DocInfo } from "../api/types";
import { forgetDoc, recentDocs, type RecentDoc } from "../lib/files";
import { errorMessage, useEditor } from "../store/editor";
import { Modal } from "./common/Modal";

const CAPABILITIES = [
  "Edit text in the document's own fonts",
  "Rewrite and reflow paragraphs",
  "OCR for scanned documents",
  "Highlights, comments, drawings, stamps",
  "Fill forms and add signatures",
  "Reorder, rotate, merge, split and crop pages",
  "Redaction and password protection",
  "Watermarks, page numbers, bookmarks",
];

const ACCEPT = "application/pdf,.pdf,image/*,.xps,.epub,.cbz,.fb2";

function formatTime(ts: number): string {
  return new Date(ts).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function StartScreen({ onOpen }: { onOpen: (doc: DocInfo) => void }) {
  const toast = useEditor((s) => s.toast);
  const [over, setOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [recent, setRecent] = useState<RecentDoc[]>(recentDocs);
  const [locked, setLocked] = useState<File | null>(null);
  const [password, setPassword] = useState("");

  const open = async (file: File, pw?: string) => {
    setLoading(true);
    try {
      const doc = await api.upload(file, pw);
      setLocked(null);
      onOpen(doc);
    } catch (error) {
      if (error instanceof ApiError && error.code === "password_required") {
        if (pw) toast("Incorrect password.", "error");
        setLocked(file);
      } else {
        toast(errorMessage(error), "error");
      }
    } finally {
      setLoading(false);
    }
  };

  const reopen = async (item: RecentDoc) => {
    try {
      onOpen(await api.info(item.id));
    } catch {
      forgetDoc(item.id);
      setRecent(recentDocs());
      toast("That document is no longer on the server. Please open the file again.", "warning");
    }
  };

  const choose = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ACCEPT;
    input.onchange = () => input.files?.[0] && void open(input.files[0]);
    input.click();
  };

  return (
    <div
      className="start"
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const file = e.dataTransfer.files[0];
        if (file) void open(file);
      }}
    >
      <header className="topbar">
        <span className="brand">PDF Studio</span>
      </header>
      <div className="start-body">
        <div className="start-inner">
          <h1>Open a document</h1>
          <p className="start-lead">PDF files, images, XPS and EPUB are supported. Files stay on this machine.</p>
          <div className={`dropzone${over ? " over" : ""}`} onClick={choose}>
            {loading ? <Loader2 size={26} className="spin" /> : <FileUp size={26} />}
            <span>{loading ? "Opening…" : "Drag a file here, or"}</span>
            <button
              className="btn primary"
              disabled={loading}
              onClick={(e) => {
                e.stopPropagation();
                choose();
              }}
            >
              Choose file…
            </button>
          </div>
          {recent.length > 0 && (
            <section className="recent">
              <h2>Recent</h2>
              <table className="recent-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th style={{ width: 70 }}>Pages</th>
                    <th style={{ width: 180 }}>Opened</th>
                    <th style={{ width: 32 }} />
                  </tr>
                </thead>
                <tbody>
                  {recent.map((item) => (
                    <tr key={item.id} onClick={() => void reopen(item)}>
                      <td>
                        <span className="name">
                          <FileText size={15} /> {item.filename}
                        </span>
                      </td>
                      <td className="muted">{item.pages}</td>
                      <td className="muted">{formatTime(item.ts)}</td>
                      <td>
                        <button
                          className="icon-btn small"
                          title="Remove from list"
                          onClick={(e) => {
                            e.stopPropagation();
                            forgetDoc(item.id);
                            setRecent(recentDocs());
                          }}
                        >
                          <X size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          <ul className="capabilities">
            {CAPABILITIES.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
      {locked && (
        <Modal
          title="Password required"
          icon={<Lock size={16} />}
          onClose={() => setLocked(null)}
          footer={
            <>
              <button className="btn" onClick={() => setLocked(null)}>Cancel</button>
              <button className="btn primary" disabled={!password || loading} onClick={() => open(locked, password)}>
                Open
              </button>
            </>
          }
        >
          <p style={{ margin: 0 }}>
            “{locked.name}” is password protected.
          </p>
          <label className="field">
            <span>Password</span>
            <input
              className="input"
              type="password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && password && open(locked, password)}
            />
          </label>
        </Modal>
      )}
    </div>
  );
}
