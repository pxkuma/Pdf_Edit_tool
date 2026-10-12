import {
  FileLock2,
  FileStack,
  FileUp,
  Highlighter,
  Loader2,
  Moon,
  PenLine,
  Signature,
  Sun,
  Trash2,
  Type,
  Wand2,
} from "lucide-react";
import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { DocInfo } from "../api/types";
import { forgetDoc, recentDocs, type RecentDoc } from "../lib/files";
import { errorMessage, useEditor } from "../store/editor";
import { Modal } from "./common/Modal";

const FEATURES = [
  { icon: <Type size={20} />, title: "Edit text in its original font", text: "Re-uses the PDF's own embedded fonts, word by word." },
  { icon: <Wand2 size={20} />, title: "Paragraph reflow", text: "Rewrite whole paragraphs; lines wrap automatically." },
  { icon: <Highlighter size={20} />, title: "Annotate", text: "Highlights, drawings, shapes, notes and stamps." },
  { icon: <Signature size={20} />, title: "Fill & sign", text: "Fill forms, add fields and place your signature." },
  { icon: <FileStack size={20} />, title: "Organize pages", text: "Reorder, rotate, insert, merge, split and crop." },
  { icon: <FileLock2 size={20} />, title: "Protect", text: "True redaction, passwords and permissions." },
];

interface StartScreenProps {
  onOpen: (doc: DocInfo) => void;
}

export function StartScreen({ onOpen }: StartScreenProps) {
  const { theme, setTheme, toast } = useEditor();
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
      toast("That document has expired on the server. Please open the file again.", "warning");
    }
  };

  const choose = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/pdf,.pdf,image/*,.xps,.epub,.cbz,.fb2";
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
      <div className="start-inner">
        <div className="start-top">
          <div className="brand">
            <span className="brand-mark">
              <PenLine size={16} />
            </span>
            <span>PDF Studio</span>
          </div>
          <button className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title="Toggle dark mode">
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
        <div className="hero">
          <div>
            <h1>Edit any PDF — word by word, in the same font.</h1>
            <p>
              Change text without breaking the layout, annotate, sign, fill forms, organize pages and protect documents. Everything
              runs on your own machine.
            </p>
            <button className="btn primary" style={{ height: 42, padding: "0 20px", fontSize: 14 }} onClick={choose} disabled={loading}>
              {loading ? <Loader2 size={17} className="spin" /> : <FileUp size={17} />} Open a PDF
            </button>
          </div>
          <div className={`dropzone${over ? " over" : ""}`} onClick={choose} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && choose()}>
            <div className="big-icon">{loading ? <Loader2 size={28} className="spin" /> : <FileUp size={28} />}</div>
            <strong style={{ fontSize: 16 }}>{loading ? "Opening…" : "Drop a PDF here"}</strong>
            <span className="muted">or click to browse · PDF, images, XPS, EPUB</span>
          </div>
        </div>
        {recent.length > 0 && (
          <section className="recent">
            <h2>Recent documents</h2>
            <div className="recent-list">
              {recent.map((item) => (
                <div key={item.id} className="row" style={{ gap: 4 }}>
                  <button className="recent-item" style={{ flex: 1 }} onClick={() => reopen(item)}>
                    <FileStack size={20} color="var(--accent)" />
                    <div>
                      <strong>{item.filename}</strong>
                      <span className="muted">
                        {item.pages} page{item.pages === 1 ? "" : "s"} · {new Date(item.ts).toLocaleString()}
                      </span>
                    </div>
                  </button>
                  <button
                    className="icon-btn small"
                    title="Remove from list"
                    onClick={() => {
                      forgetDoc(item.id);
                      setRecent(recentDocs());
                    }}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}
        <section className="features">
          {FEATURES.map((f) => (
            <div key={f.title} className="feature">
              {f.icon}
              <div>
                <strong>{f.title}</strong>
                <span>{f.text}</span>
              </div>
            </div>
          ))}
        </section>
      </div>
      {locked && (
        <Modal
          title="Password required"
          icon={<FileLock2 size={18} />}
          onClose={() => setLocked(null)}
          footer={
            <>
              <button className="btn" onClick={() => setLocked(null)}>Cancel</button>
              <button className="btn primary" disabled={!password || loading} onClick={() => open(locked, password)}>
                Unlock
              </button>
            </>
          }
        >
          <p style={{ margin: 0 }}>
            <strong>{locked.name}</strong> is protected. Enter its password to open it.
          </p>
          <input
            className="input"
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && password && open(locked, password)}
          />
        </Modal>
      )}
    </div>
  );
}
