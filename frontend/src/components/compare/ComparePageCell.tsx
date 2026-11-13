import { Loader2 } from "lucide-react";
import { memo, useEffect, useState } from "react";
import { highlightBox, type Highlight } from "../../lib/compare";

/** Keep showing the previous image until the next one has loaded, so zooming does not flash white. */
function useBufferedSrc(src: string): string | null {
  const [shown, setShown] = useState<string | null>(null);
  useEffect(() => {
    if (src === shown) return;
    if (!shown) {
      setShown(src);
      return;
    }
    let alive = true;
    const img = new Image();
    img.onload = img.onerror = () => alive && setShown(src);
    img.src = src;
    return () => {
      alive = false;
    };
  }, [src, shown]);
  return shown;
}

interface ComparePageCellProps {
  /** Null: this document has no page here (the page was added or removed). */
  size: [number, number] | null;
  /** Size of the other document's page, so the empty slot is as big. */
  slotSize: [number, number];
  zoom: number;
  src: string | null;
  label: string;
  empty: string;
  highlights: Highlight[];
}

/** One page of one document, with the differences drawn over it. */
export const ComparePageCell = memo(function ComparePageCell({ size, slotSize, zoom, src, label, empty, highlights }: ComparePageCellProps) {
  const shown = useBufferedSrc(src ?? "");
  if (!size) {
    return (
      <div className="cmp-slot" style={{ width: slotSize[0] * zoom, height: slotSize[1] * zoom }}>
        <span>{empty}</span>
      </div>
    );
  }
  return (
    <div className="cmp-page" style={{ width: size[0] * zoom, height: size[1] * zoom }}>
      {src && shown ? <img className="cmp-render" src={shown} alt={label} draggable={false} decoding="async" /> : null}
      {src && !shown && (
        <div className="cmp-loading">
          <Loader2 className="spin" size={22} />
        </div>
      )}
      {!src && <div className="cmp-loading">This page has changed since the comparison.</div>}
      {highlights.map((highlight) => (
        <div
          key={highlight.key}
          className={`cmp-hl ${highlight.tone}${highlight.marker ? " marker" : ""}${highlight.active ? " active" : ""}`}
          style={highlightBox(highlight, zoom)}
          data-change={highlight.changeId}
        />
      ))}
    </div>
  );
});
