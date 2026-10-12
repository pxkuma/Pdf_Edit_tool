import { ChevronDown, Download, FileDown, FileText, Keyboard, Loader2, Minus, Plus, Redo2, Settings2, Undo2, X } from "lucide-react";
import { api } from "../../api/client";
import { flushEdit } from "../../lib/editSession";
import { saveBlob } from "../../lib/files";
import { useEditor } from "../../store/editor";
import { Dropdown, MenuItem } from "../common/Dropdown";

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];

export async function undo(): Promise<void> {
  await flushEdit();
  const { doc, track, setDoc } = useEditor.getState();
  if (!doc?.canUndo) return;
  const info = await track(() => api.undo(doc.id));
  if (info) setDoc(info);
}

export async function redo(): Promise<void> {
  await flushEdit();
  const { doc, track, setDoc } = useEditor.getState();
  if (!doc?.canRedo) return;
  const info = await track(() => api.redo(doc.id));
  if (info) setDoc(info);
}

export async function quickDownload(): Promise<void> {
  await flushEdit();
  const { doc, track } = useEditor.getState();
  if (!doc) return;
  const file = await track(() => api.exportPdf(doc.id, { optimize: true, subset_fonts: true }));
  if (file) saveBlob(file.blob, file.filename);
}

export function TopBar({ onClose }: { onClose: () => void }) {
  const { doc, zoom, setZoom, busy, openDialog, track } = useEditor();
  if (!doc) return null;

  const download = async (fn: () => Promise<{ blob: Blob; filename: string }>) => {
    await flushEdit();
    const file = await track(fn);
    if (file) saveBlob(file.blob, file.filename);
  };

  return (
    <header className="topbar">
      <span className="brand">PDF Studio</span>
      <div className="doc-title" title={doc.filename}>
        <strong>{doc.filename}</strong>
        <span>
          {doc.pages.length} page{doc.pages.length === 1 ? "" : "s"}
          {doc.cursor > 0 ? ` · ${doc.cursor} change${doc.cursor === 1 ? "" : "s"}` : ""}
        </span>
      </div>
      <div className="topbar-actions">
        {busy > 0 && (
          <span className="status" aria-live="polite">
            <Loader2 size={14} className="spin" /> Saving
          </span>
        )}
        <button className="icon-btn" onClick={() => void undo()} disabled={!doc.canUndo} title="Undo (Ctrl+Z)">
          <Undo2 size={16} />
        </button>
        <button className="icon-btn" onClick={() => void redo()} disabled={!doc.canRedo} title="Redo (Ctrl+Y)">
          <Redo2 size={16} />
        </button>
        <span className="topbar-sep" />
        <div className="zoom-box">
          <button className="icon-btn" onClick={() => setZoom(zoom / 1.2)} title="Zoom out (Ctrl -)">
            <Minus size={15} />
          </button>
          <Dropdown
            align="right"
            trigger={({ toggle }) => (
              <button className="zoom-label" onClick={toggle} title="Zoom">
                {Math.round(zoom * 100)}%
              </button>
            )}
          >
            {(close) => (
              <>
                <MenuItem label="Fit width" hint="Ctrl+0" onClick={() => (setZoom(zoom, "width"), close())} />
                <MenuItem label="Fit page" onClick={() => (setZoom(zoom, "page"), close())} />
                <div className="menu-sep" />
                {ZOOMS.map((z) => (
                  <MenuItem key={z} label={`${z * 100}%`} onClick={() => (setZoom(z), close())} />
                ))}
              </>
            )}
          </Dropdown>
          <button className="icon-btn" onClick={() => setZoom(zoom * 1.2)} title="Zoom in (Ctrl +)">
            <Plus size={15} />
          </button>
        </div>
        <span className="topbar-sep" />
        <button className="icon-btn" onClick={() => openDialog("shortcuts")} title="Keyboard shortcuts (?)">
          <Keyboard size={16} />
        </button>
        <Dropdown
          align="right"
          trigger={({ toggle }) => (
            <div className="row" style={{ gap: 0 }}>
              <button className="btn primary" style={{ borderTopRightRadius: 0, borderBottomRightRadius: 0 }} onClick={() => void quickDownload()} title="Download (Ctrl+S)">
                <Download size={14} /> Download
              </button>
              <button
                className="btn primary"
                style={{ borderTopLeftRadius: 0, borderBottomLeftRadius: 0, padding: "0 6px", borderLeftColor: "rgb(255 255 255 / 0.35)" }}
                onClick={toggle}
                aria-label="More download options"
              >
                <ChevronDown size={14} />
              </button>
            </div>
          )}
        >
          {(close) => (
            <>
              <MenuItem icon={<Download size={15} />} label="Download PDF" hint="Ctrl+S" onClick={() => (close(), void quickDownload())} />
              <MenuItem icon={<Settings2 size={15} />} label="Export options…" onClick={() => (close(), openDialog("export"))} />
              <MenuItem icon={<FileText size={15} />} label="Export as text" onClick={() => (close(), void download(() => api.exportText(doc.id)))} />
              <MenuItem icon={<FileDown size={15} />} label="Download original file" onClick={() => (close(), void download(() => api.exportOriginal(doc.id)))} />
              <div className="menu-sep" />
              <MenuItem icon={<X size={15} />} label="Close document" onClick={() => (close(), onClose())} />
            </>
          )}
        </Dropdown>
      </div>
    </header>
  );
}
