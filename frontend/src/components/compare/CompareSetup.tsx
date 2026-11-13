import { FileUp, Loader2 } from "lucide-react";
import { useState } from "react";
import type { CompareMode, Sensitivity } from "../../api/compareTypes";
import { pickFile } from "../../lib/files";
import { useCompare } from "../../store/compare";
import { useEditor } from "../../store/editor";

const ACCEPT = "application/pdf,.pdf,image/*,.xps,.epub";

const MODES: { value: CompareMode; label: string; hint: string }[] = [
  { value: "both", label: "Text and appearance", hint: "Word changes, plus pictures, graphics and layout." },
  { value: "text", label: "Text only", hint: "Word-by-word differences. Ignores how the page looks." },
  { value: "visual", label: "Appearance only", hint: "Compares the rendered pages and marks every area that looks different." },
];

const DETAILS: { value: number; label: string }[] = [
  { value: 72, label: "Standard (72 dpi)" },
  { value: 110, label: "Detailed (110 dpi)" },
  { value: 150, label: "Fine (150 dpi, slower)" },
];

const SENSITIVITIES: { value: Sensitivity; label: string }[] = [
  { value: "low", label: "Low: only clear differences" },
  { value: "medium", label: "Normal" },
  { value: "high", label: "High: also faint differences" },
];

function Progress() {
  const progress = useCompare((s) => s.progress);
  const percent = progress && progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  return (
    <div className="field" aria-live="polite">
      <div className="row between">
        <span className="field-label">{progress?.message || "Comparing…"}</span>
        <span className="muted">{percent}%</span>
      </div>
      <div className="progress">
        <span style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

/** Choose the file to compare with, and how. */
export function CompareSetup() {
  const doc = useEditor((s) => s.doc);
  const phase = useCompare((s) => s.phase);
  const session = useCompare((s) => s.session);
  const settings = useCompare((s) => s.settings);
  const uploading = useCompare((s) => s.uploading);
  const needsPassword = useCompare((s) => s.needsPassword);
  const error = useCompare((s) => s.error);
  const hasReport = useCompare((s) => s.report !== null);
  const { chooseFile, patchSettings, run, close } = useCompare.getState(); // actions never change
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const running = phase === "running";
  const showsText = settings.mode !== "visual";
  const showsPixels = settings.mode !== "text";

  const choose = async () => {
    const picked = await pickFile(ACCEPT);
    if (!picked) return;
    setFile(picked);
    setPassword("");
    await chooseFile(picked);
  };

  return (
    <div className="cmp-setup">
      <div className="cmp-card">
        <h2>Compare documents</h2>
        <p className="muted" style={{ margin: 0 }}>
          Finds what differs between the open document and another file. Neither file is changed.
        </p>

        <div className="cmp-files">
          <div className="field">
            <span className="field-label">Original (open document)</span>
            <div className="cmp-file">{doc?.filename}</div>
          </div>
          <div className="field">
            <span className="field-label">Compare with</span>
            <div className="row">
              <div className={`cmp-file${session ? "" : " empty"}`} title={session?.filename}>
                {session ? `${session.filename} · ${session.pageCount} page${session.pageCount === 1 ? "" : "s"}` : "No file chosen"}
              </div>
              <button className="btn" onClick={() => void choose()} disabled={running || uploading}>
                {uploading ? <Loader2 size={14} className="spin" /> : <FileUp size={14} />}
                {session ? "Change…" : "Choose file…"}
              </button>
            </div>
          </div>
        </div>

        {needsPassword && file && (
          <div className="field">
            <span className="field-label">This file is password protected</span>
            <div className="row">
              <input
                className="input"
                type="password"
                autoComplete="off"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && password && void chooseFile(file, password)}
              />
              <button className="btn" disabled={!password || uploading} onClick={() => void chooseFile(file, password)}>
                Open
              </button>
            </div>
          </div>
        )}

        <label className="field">
          <span>What to compare</span>
          <select className="select" value={settings.mode} disabled={running} onChange={(e) => patchSettings({ mode: e.target.value as CompareMode })}>
            {MODES.map((mode) => (
              <option key={mode.value} value={mode.value}>
                {mode.label}
              </option>
            ))}
          </select>
          <span className="muted">{MODES.find((m) => m.value === settings.mode)?.hint}</span>
        </label>

        {showsPixels && (
          <div className="grid-2">
            <label className="field">
              <span>Detail</span>
              <select className="select" value={settings.dpi} disabled={running} onChange={(e) => patchSettings({ dpi: Number(e.target.value) })}>
                {DETAILS.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Sensitivity</span>
              <select
                className="select"
                value={settings.sensitivity}
                disabled={running}
                onChange={(e) => patchSettings({ sensitivity: e.target.value as Sensitivity })}
              >
                {SENSITIVITIES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {showsText && (
          <label className="check">
            <input type="checkbox" checked={settings.ignoreCase} disabled={running} onChange={(e) => patchSettings({ ignoreCase: e.target.checked })} />
            Ignore upper and lower case
          </label>
        )}

        {error && (
          <p className="note warn" role="alert" style={{ margin: 0 }}>
            {error}
          </p>
        )}
        {running && <Progress />}

        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={() => void close()}>
            {hasReport ? "Close compare" : "Cancel"}
          </button>
          <button className="btn primary" onClick={() => void run()} disabled={!session || running || uploading}>
            {running ? "Comparing…" : hasReport ? "Compare again" : "Compare"}
          </button>
        </div>
      </div>
    </div>
  );
}
