import { ScanText } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { Job, OcrCapabilities } from "../../api/types";
import { flushEdit } from "../../lib/editSession";
import { errorMessage, useEditor } from "../../store/editor";
import { Modal } from "../common/Modal";

const LANGUAGE_NAMES: Record<string, string> = {
  eng: "English",
  hin: "Hindi",
  deu: "German",
  fra: "French",
  spa: "Spanish",
  ita: "Italian",
  por: "Portuguese",
};

interface OcrResult {
  pages: number[];
  words: number;
  skipped: number[];
}

export function OcrDialog() {
  const { doc, openDialog, currentPage, setDoc, toast } = useEditor();
  const [info, setInfo] = useState<OcrCapabilities | null>(null);
  const [scope, setScope] = useState<"all" | "current" | "range">("all");
  const [range, setRange] = useState("");
  const [languages, setLanguages] = useState<string[]>(["eng"]);
  const [dpi, setDpi] = useState(300);
  const [force, setForce] = useState(false);
  const [job, setJob] = useState<Job<OcrResult> | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    api
      .ocrInfo()
      .then((data) => {
        setInfo(data);
        if (data.default) setLanguages([data.default]);
      })
      .catch((error: unknown) => toast(errorMessage(error), "error"));
    return () => window.clearTimeout(timer.current);
  }, [toast]);

  if (!doc) return null;
  const running = job?.status === "running";
  const close = () => {
    if (!running) openDialog(null);
  };

  const poll = (jobId: string) => {
    timer.current = window.setTimeout(async () => {
      try {
        const next = await api.job<OcrResult>(jobId);
        setJob(next);
        if (next.status === "running") {
          poll(jobId);
          return;
        }
        if (next.status === "error") {
          toast(next.error || "OCR failed.", "error");
          return;
        }
        if (next.document) setDoc(next.document);
        const result = next.result;
        const skipped = result?.skipped.length ? ` ${result.skipped.length} page(s) changed during OCR and were skipped.` : "";
        toast(result && result.pages.length ? `Text recognised: ${result.words} words on ${result.pages.length} page(s).${skipped}` : next.message, "success");
        openDialog(null);
      } catch (error) {
        toast(errorMessage(error), "error");
        setJob(null);
      }
    }, 600);
  };

  const start = async () => {
    await flushEdit();
    const pages = scope === "all" ? null : scope === "current" ? String(currentPage + 1) : range;
    try {
      const started = await api.startOcr(doc.id, { pages, language: languages.join("+"), dpi, force });
      setJob(started as Job<OcrResult>);
      poll(started.id);
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  };

  const toggleLanguage = (code: string) =>
    setLanguages((current) => (current.includes(code) ? current.filter((c) => c !== code) : [...current, code]));

  const percent = job && job.total ? Math.round((job.done / job.total) * 100) : 0;

  return (
    <Modal
      title="Recognise text (OCR)"
      icon={<ScanText size={16} />}
      onClose={close}
      footer={
        <>
          <button className="btn" onClick={close} disabled={running}>
            Cancel
          </button>
          <button className="btn primary" onClick={start} disabled={!info?.available || running || !languages.length || (scope === "range" && !range.trim())}>
            {running ? "Recognising…" : "Run OCR"}
          </button>
        </>
      }
    >
      {info && !info.available && (
        <p className="note warn" style={{ margin: 0 }}>
          OCR is not available on this server. Run PDF Studio with Docker, which includes Tesseract.
        </p>
      )}
      <p className="muted" style={{ margin: 0 }}>
        Adds an invisible text layer over scanned pages. The page keeps its appearance; its text becomes searchable, selectable and editable.
      </p>
      <label className="field">
        <span>Pages</span>
        <div className="row">
          <select className="select" style={{ width: 170 }} value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
            <option value="all">All pages</option>
            <option value="current">Current page ({currentPage + 1})</option>
            <option value="range">Page range</option>
          </select>
          {scope === "range" && <input className="input" placeholder="e.g. 1-3, 7" value={range} onChange={(e) => setRange(e.target.value)} />}
        </div>
      </label>
      <div className="field">
        <span className="field-label">Document language</span>
        <div className="row wrap" style={{ gap: 14 }}>
          {(info?.languages ?? []).map((code) => (
            <label key={code} className="check">
              <input type="checkbox" checked={languages.includes(code)} onChange={() => toggleLanguage(code)} />
              {LANGUAGE_NAMES[code] ?? code}
            </label>
          ))}
        </div>
      </div>
      <div className="grid-2">
        <label className="field">
          <span>Resolution</span>
          <select className="select" value={dpi} onChange={(e) => setDpi(Number(e.target.value))}>
            <option value={200}>200 dpi (faster)</option>
            <option value={300}>300 dpi (recommended)</option>
            <option value={400}>400 dpi (small print)</option>
          </select>
        </label>
        <label className="check" style={{ alignSelf: "end", height: 28 }}>
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
          Redo pages that already have OCR text
        </label>
      </div>
      {job && (
        <div className="field">
          <div className="row between">
            <span className="field-label">{job.message || "Starting…"}</span>
            <span className="muted">
              {job.done} / {job.total || "…"}
            </span>
          </div>
          <div className="progress">
            <span style={{ width: `${percent}%` }} />
          </div>
        </div>
      )}
    </Modal>
  );
}
