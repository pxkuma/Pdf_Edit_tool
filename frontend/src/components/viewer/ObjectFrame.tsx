import { useEffect, useRef, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import type { Rect } from "../../api/types";
import type { Handle } from "../../lib/geometry";
import { NUDGE } from "../../lib/snap";

interface ObjectFrameProps {
  rect: Rect; // where the object is shown now (page points)
  original: Rect; // where it really is
  zoom: number;
  renderSrc: string | null;
  pageSize: [number, number];
  background: string; // colour that hides the original while it is being moved
  label: string;
  onBodyDown: (event: ReactPointerEvent) => void;
  onHandleDown: (handle: Handle, event: ReactPointerEvent) => void;
  onNudge: (dx: number, dy: number) => void;
  onDelete: () => void;
  onDeselect: () => void;
}

const HANDLES: Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

const box = (r: Rect, zoom: number): CSSProperties => ({
  left: r[0] * zoom,
  top: r[1] * zoom,
  width: Math.max(1, (r[2] - r[0]) * zoom),
  height: Math.max(1, (r[3] - r[1]) * zoom),
});

/**
 * Selection frame of an image or vector graphic: drag the body to move, any of
 * the eight handles to resize. While it changes, the real page pixels are
 * shown at the new place. Arrow keys nudge (Shift: 10 pt), Delete removes it.
 */
export function ObjectFrame(props: ObjectFrameProps) {
  const { rect, original, zoom, renderSrc, pageSize, background, label } = props;
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => ref.current?.focus({ preventScroll: true }), []);

  const changed = rect.some((v, i) => Math.abs(v - original[i]) > 0.01);
  const sx = (rect[2] - rect[0]) / Math.max(0.01, original[2] - original[0]);
  const sy = (rect[3] - rect[1]) / Math.max(0.01, original[3] - original[1]);
  const ghost: CSSProperties = {
    ...box(rect, zoom),
    backgroundImage: renderSrc ? `url(${renderSrc})` : undefined,
    backgroundSize: `${pageSize[0] * zoom * sx}px ${pageSize[1] * zoom * sy}px`,
    backgroundPosition: `${-original[0] * zoom * sx}px ${-original[1] * zoom * sy}px`,
  };

  const onKeyDown = (event: KeyboardEvent) => {
    const arrow = NUDGE[event.key];
    if (arrow) {
      event.preventDefault();
      const step = event.shiftKey ? 10 : 1;
      props.onNudge(arrow[0] * step, arrow[1] * step);
    } else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      props.onDelete();
    } else if (event.key === "Escape") {
      props.onDeselect();
    }
    event.stopPropagation();
  };

  return (
    <>
      {changed && <div className="obj-cover" style={{ ...box(original, zoom), background }} />}
      {changed && <div className="obj-ghost" style={ghost} />}
      <div
        ref={ref}
        className="obj-frame"
        style={box(rect, zoom)}
        tabIndex={0}
        role="group"
        aria-label={`${label} — drag to move, handles resize, Delete removes`}
        onKeyDown={onKeyDown}
        onPointerDown={(e) => {
          e.stopPropagation();
          props.onBodyDown(e);
        }}
      >
        {HANDLES.map((handle) => (
          <span
            key={handle}
            className={`handle ${handle}`}
            onPointerDown={(e) => {
              e.stopPropagation();
              props.onHandleDown(handle, e);
            }}
          />
        ))}
      </div>
    </>
  );
}
