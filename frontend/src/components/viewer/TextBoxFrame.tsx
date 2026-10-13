import type { KeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode, RefObject } from "react";
import type { CornerHandle, SideHandle } from "../../lib/textBox";
import { startDrag } from "./usePointer";

export type BoxGesture = "move" | SideHandle | CornerHandle;

interface TextBoxFrameProps {
  frameRef?: RefObject<HTMLDivElement>;
  /** Box position and width in CSS pixels; the height follows the text. */
  left: number;
  top: number;
  width: number;
  autoWidth: boolean;
  /** Selected (not typing): the whole box is a drag handle and keys act on the box. */
  selected?: boolean;
  /** Called when a drag starts; returns the live update for pointer deltas (CSS px). Alt = no snapping. */
  onGesture: (gesture: BoxGesture, clientX: number, clientY: number) => (dx: number, dy: number, free: boolean) => void;
  onGestureEnd: () => void;
  onAutoWidth: () => void;
  onKeyDown?: (event: KeyboardEvent) => void;
  children: ReactNode;
}

const SIDES: SideHandle[] = ["w", "e"];
const CORNERS: CornerHandle[] = ["sw", "se"];

/**
 * A movable, resizable frame around an inline text editor.
 * Border (or the whole box when selected): move. Side handles: box width (text
 * wraps inside it). Corner handles: scale the text. Double-clicking a side
 * handle returns to auto width. Moving and resizing snap to other text and the
 * page centre; hold Alt to move freely.
 */
export function TextBoxFrame(props: TextBoxFrameProps) {
  const { frameRef, left, top, width, autoWidth, selected, onGesture, onGestureEnd, onAutoWidth, onKeyDown, children } = props;
  const begin = (gesture: BoxGesture) => (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    const update = onGesture(gesture, event.clientX, event.clientY);
    startDrag(event, (dx, dy, e) => update(dx, dy, e.altKey), () => onGestureEnd());
  };

  return (
    <div
      ref={frameRef}
      className={`tbox${autoWidth ? " auto" : ""}${selected ? " selected" : ""}`}
      style={{ left, top, width }}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div className="tbox-move" title={selected ? "Drag to move · double-click to edit the text" : "Drag to move"} onPointerDown={begin("move")} />
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
