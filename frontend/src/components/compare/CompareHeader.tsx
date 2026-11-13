import { ArrowLeft, ChevronDown, ChevronUp, Maximize, Minus, Plus, SlidersHorizontal } from "lucide-react";
import { useMemo } from "react";
import { summaryText, visibleChanges } from "../../lib/compare";
import { useCompare } from "../../store/compare";
import { useEditor } from "../../store/editor";

/** Title bar of the Compare view: what is compared, how many differences, and the way back to editing. */
export function CompareHeader() {
  const doc = useEditor((s) => s.doc);
  const phase = useCompare((s) => s.phase);
  const report = useCompare((s) => s.report);
  const session = useCompare((s) => s.session);
  const filters = useCompare((s) => s.filters);
  const zoom = useCompare((s) => s.zoom);
  const fit = useCompare((s) => s.fit);
  const { step, setZoom, backToSetup, close } = useCompare.getState(); // actions never change
  const shown = useMemo(() => visibleChanges(report, filters), [report, filters]);
  const total = report?.totals.changes ?? 0;
  const ready = phase === "ready" && report !== null;

  return (
    <header className="topbar cmp-header">
      <button className="btn" onClick={() => void close()} title="Close the comparison and go back to editing">
        <ArrowLeft size={14} /> Back to editing
      </button>
      <div className="doc-title" title={`${doc?.filename ?? ""} and ${session?.filename ?? ""}`}>
        <strong>Compare documents</strong>
        <span>
          {doc?.filename}
          {session ? ` ↔ ${session.filename}` : ""}
        </span>
      </div>

      {ready && (
        <>
          <div className="cmp-summary" aria-live="polite">
            <strong>{summaryText(shown)}</strong>
            {shown.length !== total && <span>{` (${total} in all)`}</span>}
          </div>
          <div className="cmp-legend" aria-hidden="true">
            <span className="delete">Deleted</span>
            <span className="insert">Added</span>
            <span className="replace-new">Replaced</span>
            <span className="visual">Image or layout</span>
          </div>
        </>
      )}

      <div className="topbar-actions">
        {ready && (
          <>
            <button className="icon-btn" onClick={() => step(-1)} disabled={!shown.length} title="Previous difference (P)" aria-label="Previous difference">
              <ChevronUp size={16} />
            </button>
            <button className="icon-btn" onClick={() => step(1)} disabled={!shown.length} title="Next difference (N)" aria-label="Next difference">
              <ChevronDown size={16} />
            </button>
            <span className="topbar-sep" />
            <div className="zoom-box">
              <button className="icon-btn" onClick={() => setZoom(zoom / 1.2)} title="Zoom out" aria-label="Zoom out">
                <Minus size={15} />
              </button>
              <span className="zoom-label" aria-live="off">
                {Math.round(zoom * 100)}%
              </span>
              <button className="icon-btn" onClick={() => setZoom(zoom * 1.2)} title="Zoom in" aria-label="Zoom in">
                <Plus size={15} />
              </button>
              <button className={`icon-btn${fit ? " active" : ""}`} onClick={() => setZoom(zoom, true)} title="Fit both pages to the width" aria-label="Fit width" aria-pressed={fit}>
                <Maximize size={15} />
              </button>
            </div>
            <span className="topbar-sep" />
            <button className="btn" onClick={backToSetup}>
              <SlidersHorizontal size={14} /> Options
            </button>
          </>
        )}
      </div>
    </header>
  );
}
