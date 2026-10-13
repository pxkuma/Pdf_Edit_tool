import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import type { CornerHandle, SideHandle } from "../../lib/textBox";
import { startDrag } from "./usePointer";

export type BoxGesture = "move" | SideHandle | CornerHandle;

interface TextBoxFrameProps {
  /** Box position and width in CSS pixels; the height follows the text. */
  left: number;
  top: number;
  width: number;
  autoWidth: boolean;
  /** Called when a drag starts; returns the live update for pointer deltas (CSS px). */
  onGesture: (gesture: BoxGesture) => (dx: number, dy: number) => void;
  onGestureEnd: () => void;
  onAutoWidth: () => void;
  children: ReactNode;
}

const SIDES: SideHandle[] = ["w", "e"];
const CORNERS: CornerHandle[] = ["sw", "se"];

/**
 * A movable, resizable frame around an inline text editor.
 * Border: move. Side handles: box width (text wraps inside it). Corner handles:
 * scale the text. Double-clicking a side handle returns to auto width.
 */
export function TextBoxFrame({ left, top, width, autoWidth, onGesture, onGestureEnd, onAutoWidth, children }: TextBoxFrameProps) {
  const begin = (gesture: BoxGesture) => (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    const update = onGesture(gesture);
    startDrag(event, (dx, dy) => update(dx, dy), () => onGestureEnd());
  };

  return (
    <div
      className={`tbox${autoWidth ? " auto" : ""}`}
      style={{ left, top, width }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div className="tbox-move" title="Drag to move" onPointerDown={begin("move")} />
      {children}
      {SIDES.map((side) => (
        <div
          key={side}
          className={`tbox-handle side ${side}`}
          title={autoWidth ? "Drag to set a fixed width (text wraps inside)" : "Drag to change the width · double-click for auto width"}
          onPointerDown={begin(side)}
          onDoubleClick={onAutoWidth}
        />
      ))}
      {CORNERS.map((corner) => (
        <div key={corner} className={`tbox-handle corner ${corner}`} title="Drag to resize the text" onPointerDown={begin(corner)} />
      ))}
    </div>
  );
}
