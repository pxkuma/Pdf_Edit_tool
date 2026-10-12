import { Download, FileImage, FileOutput, Lock, Scissors, Settings2 } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { flushEdit } from "../../lib/editSession";
import { saveBlob } from "../../lib/files";
import { useEditor } from "../../store/editor";
import { Modal } from "../common/Modal";

type Tab = "pdf" | "protect" | "images" | "extract" | "split";

export function ExportDialog({ initialTab = "pdf" }: { initialTab?: Tab }) {
  const { doc, openDialog, track, selectedPages, toast } = useEditor();
  const [tab, setTab] = useState<Tab>(initialTab);
  const [pdf, setPdf] = useState({
    optimize: true,
    subset_fonts: true,
    compress_images: false,
    image_dpi: 150,
    image_quality: 75,
    flatten_annotations: false,
    flatten_forms: false,
    remove_metadata: false,
  });
  const [security, setSecurity] = useState({
    user_password: "",
    owner_password: "",
    allow_print: true,
    allow_copy: true,
    allow_modify: true,
    allow_annotate: true,
  });
  const [images, setImages] = useState({ pages: "", dpi: 150, format: "png" as "png" | "jpg" });
  const [extractPages, setExtractPages] = useState(selectedPages.length ? selectedPages.map((p) => p + 1).join(",") : "");
  const [every, setEvery] = useState(1);
  if (!doc) return null;
  const close = () => openDialog(null);

  const download = async (fn: () => Promise<{ blob: Blob; filename: string }>) => {
    await flushEdit();
    const file = await track(fn);
    if (file) {
      saveBlob(file.blob, file.filename);
      toast(`Saved ${file.filename}`, "success");
      close();
    }
  };

  const exportPdf = () => {
    if (tab === "protect" && !security.user_password && !security.owner_password) {
      toast("Enter a password first.", "warning");
      return;
    }
    const options = tab === "protect" ? { ...pdf, ...security } : pdf;
    void download(() => api.exportPdf(doc.id, options));
  };

  const check = (label: string, value: boolean, onChange: (v: boolean) => void, hint?: string) => (
    <label className="check" title={hint}>
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} /> {label}
    </label>
  );

  const footer = (
    <>
      <button className="btn" onClick={close}>Cancel</button>
      {(tab === "pdf" || tab === "protect") && (
        <button className="btn primary" onClick={exportPdf}>
          <Download size={15} /> Download PDF
        </button>
      )}
      {tab === "images" && (
        <button className="btn primary" onClick={() => void download(() => api.exportImages(doc.id, images))}>
          <FileImage size={15} /> Export images
        </button>
      )}
      {tab === "extract" && (
        <button className="btn primary" disabled={!extractPages.trim()} onClick={() => void download(() => api.exportExtract(doc.id, extractPages))}>
          <FileOutput size={15} /> Extract pages
        </button>
      )}
      {tab === "split" && (
        <button className="btn primary" onClick={() => void download(() => api.exportSplit(doc.id, every))}>
          <Scissors size={15} /> Split & download
        </button>
      )}
    </>
  );

  return (
    <Modal title="Export & save" icon={<Settings2 size={18} />} onClose={close} footer={footer} wide>
      <div className="tabs">
        {(
          [
            ["pdf", "PDF options"],
            ["protect", "Password"],
            ["images", "Images"],
            ["extract", "Extract pages"],
            ["split", "Split"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button key={key} className={tab === key ? "on" : ""} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>
      {(tab === "pdf" || tab === "protect") && (
        <div className="grid-2">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <strong>Optimization</strong>
            {check("Optimize file structure", pdf.optimize, (v) => setPdf({ ...pdf, optimize: v }), "Remove unused objects and compress streams")}
            {check("Subset fonts (smaller file)", pdf.subset_fonts, (v) => setPdf({ ...pdf, subset_fonts: v }))}
            {check("Compress images", pdf.compress_images, (v) => setPdf({ ...pdf, compress_images: v }))}
            {pdf.compress_images && (
              <div className="grid-2">
                <label className="field">
                  <span>Target DPI</span>
                  <input className="input small" type="number" min={36} max={600} value={pdf.image_dpi} onChange={(e) => setPdf({ ...pdf, image_dpi: Number(e.target.value) || 150 })} />
                </label>
                <label className="field">
                  <span>JPEG quality</span>
                  <input className="input small" type="number" min={10} max={95} value={pdf.image_quality} onChange={(e) => setPdf({ ...pdf, image_quality: Number(e.target.value) || 75 })} />
                </label>
              </div>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <strong>Content</strong>
            {check("Flatten annotations", pdf.flatten_annotations, (v) => setPdf({ ...pdf, flatten_annotations: v }))}
            {check("Flatten form fields", pdf.flatten_forms, (v) => setPdf({ ...pdf, flatten_forms: v }))}
            {check("Remove metadata", pdf.remove_metadata, (v) => setPdf({ ...pdf, remove_metadata: v }))}
          </div>
        </div>
      )}
      {tab === "protect" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="row" style={{ gap: 6 }}>
            <Lock size={15} /> <strong>Password protection (AES-256)</strong>
          </div>
          <div className="grid-2">
            <label className="field">
              <span>Password to open</span>
              <input className="input" type="password" autoComplete="new-password" value={security.user_password} onChange={(e) => setSecurity({ ...security, user_password: e.target.value })} />
            </label>
            <label className="field">
              <span>Owner password (permissions)</span>
              <input className="input" type="password" autoComplete="new-password" placeholder="Same as above" value={security.owner_password} onChange={(e) => setSecurity({ ...security, owner_password: e.target.value })} />
            </label>
          </div>
          <div className="grid-2">
            {check("Allow printing", security.allow_print, (v) => setSecurity({ ...security, allow_print: v }))}
            {check("Allow copying text", security.allow_copy, (v) => setSecurity({ ...security, allow_copy: v }))}
            {check("Allow editing", security.allow_modify, (v) => setSecurity({ ...security, allow_modify: v }))}
            {check("Allow comments & forms", security.allow_annotate, (v) => setSecurity({ ...security, allow_annotate: v }))}
          </div>
          <p className="note">The editor keeps an unencrypted working copy; only the downloaded file is protected.</p>
        </div>
      )}
      {tab === "images" && (
        <div className="grid-3">
          <label className="field">
            <span>Pages</span>
            <input className="input" placeholder="All (e.g. 1-3,5)" value={images.pages} onChange={(e) => setImages({ ...images, pages: e.target.value })} />
          </label>
          <label className="field">
            <span>Resolution (DPI)</span>
            <select className="select" value={images.dpi} onChange={(e) => setImages({ ...images, dpi: Number(e.target.value) })}>
              {[72, 96, 150, 200, 300, 600].map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Format</span>
            <select className="select" value={images.format} onChange={(e) => setImages({ ...images, format: e.target.value as "png" | "jpg" })}>
              <option value="png">PNG</option>
              <option value="jpg">JPEG</option>
            </select>
          </label>
        </div>
      )}
      {tab === "extract" && (
        <label className="field">
          <span>Pages to extract into a new PDF</span>
          <input className="input" placeholder="e.g. 1-3,5,8-" value={extractPages} onChange={(e) => setExtractPages(e.target.value)} />
        </label>
      )}
      {tab === "split" && (
        <label className="field">
          <span>Split every N pages (downloads a ZIP)</span>
          <input className="input" type="number" min={1} max={doc.pages.length} value={every} onChange={(e) => setEvery(Math.max(1, Number(e.target.value) || 1))} />
          <span className="muted">Creates {Math.ceil(doc.pages.length / every)} file(s).</span>
        </label>
      )}
    </Modal>
  );
}
