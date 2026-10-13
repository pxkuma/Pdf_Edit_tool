import type { CSSProperties } from "react";
import type { Rect } from "../../api/types";
import { useBackgrounds } from "../../lib/background";
import type { PushCandidate, PushSelection } from "../../lib/push";

interface PushPreviewProps {
  selection: PushSelection;
  conflicts: string[]; // kept items that moved content lands on
  dy: number; // points
  zoom: number;
  renderSrc: string | null;
  pageSize: [number, number];
  onToggle: (item: PushCandidate, move: boolean) => void;
}

const PAD = 1.5;

function box(rect: Rect, zoom: number, dy = 0): CSSProperties {
  return {
    left: (rect[0] - PAD) * zoom,
    top: (rect[1] - PAD + dy) * zoom,
    width: (rect[2] - rect[0] + PAD * 2) * zoom,
    height: (rect[3] - rect[1] + PAD * 2) * zoom,
  };
}

/**
 * Live preview of content moving below a growing text box: each moving item is
 * shown at its destination using the actual page rendering, and the place it
 * leaves is blanked. Click a moving item to keep it in place, a dotted one to
 * move it too.
 */
export function PushPreview({ selection, conflicts, dy, zoom, renderSrc, pageSize, onToggle }: PushPreviewProps) {
  const backgrounds = useBackgrounds(renderSrc, pageSize[0], selection.moving.map((m) => m.bbox));
  if (Math.abs(dy) < 0.05) return null;
  const ghost = (rect: Rect): CSSProperties => ({
    ...box(rect, zoom, dy),
    backgroundImage: renderSrc ? `url(${renderSrc})` : undefined,
    backgroundSize: `${pageSize[0] * zoom}px ${pageSize[1] * zoom}px`,
    backgroundPosition: `${-(rect[0] - PAD) * zoom}px ${-(rect[1] - PAD) * zoom}px`,
  });

  return (
    <div className="push-layer">
      {selection.moving.map((item, i) => (
        <div key={`c-${item.key}`} className="push-cover" style={{ ...box(item.bbox, zoom), background: backgrounds[i] }} />
      ))}
      {selection.moving.map((item) => (
        <div
          key={`g-${item.key}`}
          className="push-ghost"
          style={ghost(item.bbox)}
          title="Moves with the text box — click to keep it in place"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => onToggle(item, false)}
        />
      ))}
      {selection.kept.map((item) => (
        <div
          key={`k-${item.key}`}
          className={conflicts.includes(item.key) ? "push-kept conflict" : "push-kept"}
          style={box(item.bbox, zoom)}
          title={
            conflicts.includes(item.key)
              ? "Moved content will overlap this — click to move it too"
              : "Stays in place — click to move it with the text box"
          }
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => onToggle(item, true)}
        />
      ))}
    </div>
  );
}
