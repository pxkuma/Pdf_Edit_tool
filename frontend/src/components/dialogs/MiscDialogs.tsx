import { FilePlus2, Info, Keyboard } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Metadata } from "../../api/types";
import { pickFile } from "../../lib/files";
import { useEditor } from "../../store/editor";
import { Modal } from "../common/Modal";

export function MetadataDialog() {
  const { doc, openDialog, run } = useEditor();
  const [meta, setMeta] = useState<Metadata | null>(null);
  useEffect(() => {
    if (!doc) return;
    api.metadata(doc.id).then(setMeta).catch(() => setMeta(null));
  }, [doc]);
  if (!doc) return null;
  const close = () => openDialog(null);
  const fields: [keyof Metadata, string][] = [
    ["title", "Title"],
    ["author", "Author"],
    ["subject", "Subject"],
    ["keywords", "Keywords"],
    ["creator", "Creator application"],
    ["producer", "Producer"],
  ];
  return (
    <Modal
      title="Document properties"
      icon={<Info size={18} />}
      onClose={close}
      footer={
        <>
          <button className="btn" onClick={close}>Cancel</button>
          <button
            className="btn primary"
            disabled={!meta}
            onClick={async () => {
              close();
              if (meta) await run(() => api.setMetadata(doc.id, meta), "Properties saved");
            }}
          >
            Save
          </button>
        </>
      }
    >
      {!meta ? (
        <div className="empty">Loading…</div>
      ) : (
        fields.map(([key, label]) => (
          <label key={key} className="field">
            <span>{label}</span>
            <input className="input" value={meta[key]} onChange={(e) => setMeta({ ...meta, [key]: e.target.value })} />
          </label>
        ))
      )}
    </Modal>
  );
}

export function InsertPagesDialog() {
  const { doc, openDialog, run, currentPage } = useEditor();
  const [position, setPosition] = useState<"before" | "after" | "start" | "end">("after");
  const [size, setSize] = useState("same");
  const [landscape, setLandscape] = useState(false);
  const [count, setCount] = useState(1);
  if (!doc) return null;
  const close = () => openDialog(null);
  const at = position === "start" ? 0 : position === "end" ? doc.pages.length : position === "before" ? currentPage : currentPage + 1;

  const insertBlank = async () => {
    close();
    for (let i = 0; i < count; i++) {
      const before = useEditor.getState().doc?.pages.length ?? 0;
      await run(() => api.insertBlank(doc.id, at + i, size, landscape));
      if ((useEditor.getState().doc?.pages.length ?? 0) === before) break; // failed: stop
    }
  };

  const insertFile = async () => {
    const file = await pickFile("application/pdf,image/*,.pdf,.xps,.epub,.cbz");
    if (!file) return;
    close();
    await run(() => api.insertFile(doc.id, at, file), `Inserted ${file.name}`);
  };

  return (
    <Modal title="Insert pages" icon={<FilePlus2 size={18} />} onClose={close}>
      <label className="field">
        <span>Where</span>
        <select className="select" value={position} onChange={(e) => setPosition(e.target.value as typeof position)}>
          <option value="before">Before current page ({currentPage + 1})</option>
          <option value="after">After current page ({currentPage + 1})</option>
          <option value="start">At the beginning</option>
          <option value="end">At the end</option>
        </select>
      </label>
      <div className="note">
        <strong style={{ color: "var(--text)" }}>Blank page</strong>
        <div className="grid-3" style={{ marginTop: 8 }}>
          <select className="select small" value={size} onChange={(e) => setSize(e.target.value)}>
            <option value="same">Same size</option>
            <option value="a4">A4</option>
            <option value="letter">Letter</option>
            <option value="legal">Legal</option>
            <option value="a3">A3</option>
            <option value="a5">A5</option>
          </select>
          <label className="check">
            <input type="checkbox" checked={landscape} disabled={size === "same"} onChange={(e) => setLandscape(e.target.checked)} /> Landscape
          </label>
          <input className="input small" type="number" min={1} max={50} value={count} onChange={(e) => setCount(Math.max(1, Math.min(50, Number(e.target.value) || 1)))} />
        </div>
        <button className="btn small primary" style={{ marginTop: 10 }} onClick={insertBlank}>
          Insert {count} blank page{count > 1 ? "s" : ""}
        </button>
      </div>
      <div className="note">
        <strong style={{ color: "var(--text)" }}>From a file</strong>
        <p style={{ margin: "6px 0 10px" }}>Merge another PDF, or add images (PNG, JPEG…) as new pages.</p>
        <button className="btn small primary" onClick={insertFile}>
          Choose file…
        </button>
      </div>
    </Modal>
  );
}

const SHORTCUTS: [string, string][] = [
  ["Ctrl + Z", "Undo"],
  ["Ctrl + Y / Ctrl + Shift + Z", "Redo"],
  ["Ctrl + S", "Download PDF"],
  ["Ctrl + F", "Find & replace"],
  ["Ctrl + + / Ctrl + -", "Zoom in / out"],
  ["Ctrl + 0", "Fit width"],
  ["Ctrl + scroll", "Zoom"],
  ["V", "Select tool"],
  ["T", "Edit text"],
  ["A", "Add text"],
  ["H", "Highlight"],
  ["D", "Draw"],
  ["N", "Sticky note"],
  ["Space (hold)", "Pan"],
  ["Delete", "Delete selected annotation/image"],
  ["Esc", "Cancel / back to Select"],
  ["Enter", "Apply text edit"],
  ["PgUp / PgDn", "Previous / next page"],
];

export function ShortcutsDialog() {
  const openDialog = useEditor((s) => s.openDialog);
  return (
    <Modal title="Keyboard shortcuts" icon={<Keyboard size={18} />} onClose={() => openDialog(null)}>
      <div className="list">
        {SHORTCUTS.map(([keys, label]) => (
          <div key={keys} className="row between" style={{ padding: "5px 2px" }}>
            <span>{label}</span>
            <span className="row" style={{ gap: 4 }}>
              {keys.split(" ").map((k, i) => (k === "+" || k === "/" ? <span key={i} className="muted">{k}</span> : <span key={i} className="kbd">{k}</span>))}
            </span>
          </div>
        ))}
      </div>
    </Modal>
  );
}
