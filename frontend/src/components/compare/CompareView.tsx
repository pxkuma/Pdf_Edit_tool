import { useEffect } from "react";
import { isStale } from "../../lib/compare";
import { useCompare } from "../../store/compare";
import { useEditor } from "../../store/editor";
import { CompareHeader } from "./CompareHeader";
import { CompareRows } from "./CompareRows";
import { CompareSetup } from "./CompareSetup";
import { CompareSidebar } from "./CompareSidebar";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return Boolean(el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)));
}

/** N and P (or Alt+Down / Alt+Up) jump to the next and previous difference. */
function useDifferenceKeys(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTyping(event.target) || event.ctrlKey || event.metaKey) return;
      const key = event.key.toLowerCase();
      const next = key === "n" || (event.altKey && key === "arrowdown");
      const previous = key === "p" || (event.altKey && key === "arrowup");
      if (!next && !previous) return;
      event.preventDefault();
      useCompare.getState().step(next ? 1 : -1);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}

function StaleNotice() {
  const report = useCompare((s) => s.report);
  const version = useEditor((s) => s.doc?.version);
  const backToSetup = useCompare((s) => s.backToSetup);
  if (!isStale(report, version)) return null;
  return (
    <div className="viewer-notice" role="status">
      <span>The document has changed since this comparison, so the left pages may not match the marks.</span>
      <button className="btn small" onClick={backToSetup}>
        Compare again
      </button>
    </div>
  );
}

/** Side-by-side comparison of the open document and a second file. Replaces the editor until closed. */
export function CompareView() {
  const phase = useCompare((s) => s.phase);
  useDifferenceKeys(phase === "ready");

  return (
    <div className="compare-app">
      <CompareHeader />
      {phase === "ready" ? (
        <>
          <StaleNotice />
          <div className="cmp-workspace">
            <CompareSidebar />
            <CompareRows />
          </div>
        </>
      ) : (
        <CompareSetup />
      )}
    </div>
  );
}
