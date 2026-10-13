import { useCallback, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import type { Point } from "../../api/types";

/** Converts pointer events into page coordinates (PDF points, display space). */
export function usePagePoint(ref: RefObject<HTMLElement>, zoom: number) {
  return useCallback(
    (event: { clientX: number; clientY: number }): Point => {
      const rect = ref.current?.getBoundingClientRect();
      if (!rect) return [0, 0];
      return [(event.clientX - rect.left) / zoom, (event.clientY - rect.top) / zoom];
    },
    [ref, zoom],
  );
}

/** Follow the pointer from a start position until it is released (no element needed). */
export function trackPointer(
  startX: number,
  startY: number,
  onMove: (dx: number, dy: number, e: PointerEvent) => void,
  onEnd: (dx: number, dy: number, e: PointerEvent) => void,
): void {
  const move = (e: PointerEvent) => onMove(e.clientX - startX, e.clientY - startY, e);
  const up = (e: PointerEvent) => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    window.removeEventListener("pointercancel", up);
    onEnd(e.clientX - startX, e.clientY - startY, e);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
}

/** Track a drag with pointer capture; returns cleanup-free handlers. */
export function startDrag(
  event: ReactPointerEvent,
  onMove: (dx: number, dy: number, e: PointerEvent) => void,
  onEnd: (dx: number, dy: number, e: PointerEvent) => void,
): void {
  event.preventDefault();
  event.stopPropagation();
  const startX = event.clientX;
  const startY = event.clientY;
  const target = event.currentTarget as HTMLElement;
  target.setPointerCapture?.(event.pointerId);
  const move = (e: PointerEvent) => onMove(e.clientX - startX, e.clientY - startY, e);
  const up = (e: PointerEvent) => {
    target.releasePointerCapture?.(event.pointerId);
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    onEnd(e.clientX - startX, e.clientY - startY, e);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}
