import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import { api } from "../../api/client";
import type { Point, Rect } from "../../api/types";
import { flushEdit } from "../../lib/editSession";
import { cssRect, normRect, rectHeight, rectWidth } from "../../lib/geometry";
import { useEditor, type Tool } from "../../store/editor";
import { NewTextEditor } from "./NewTextEditor";
import { ToolPopover, type PopoverState } from "./ToolPopover";
import { usePagePoint } from "./usePointer";

interface DrawLayerProps {
  docId: string;
  page: number;
  zoom: number;
  tool: Tool;
  pageSize: [number, number];
  pageRef: RefObject<HTMLDivElement>;
}

const RECT_TOOLS: Tool[] = ["rect", "ellipse", "textbox", "whiteout", "redact", "eraseText", "crop", "fieldText", "fieldCheckbox", "image"];
const LINE_TOOLS: Tool[] = ["line", "arrow"];

function arrowHead(a: Point, b: Point, size: number): string {
  const angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
  const p1: Point = [b[0] - size * Math.cos(angle - 0.45), b[1] - size * Math.sin(angle - 0.45)];
  const p2: Point = [b[0] - size * Math.cos(angle + 0.45), b[1] - size * Math.sin(angle + 0.45)];
  return `M ${p1[0]} ${p1[1]} L ${b[0]} ${b[1]} L ${p2[0]} ${p2[1]}`;
}

export function DrawLayer({ docId, page, zoom, tool, pageSize, pageRef }: DrawLayerProps) {
  const toPoint = usePagePoint(pageRef, zoom);
  const [start, setStart] = useState<Point | null>(null);
  const [current, setCurrent] = useState<Point | null>(null);
  const [path, setPath] = useState<Point[]>([]);
  const [hover, setHover] = useState<Point | null>(null);
  const [popover, setPopover] = useState<PopoverState | null>(null);
  const [newText, setNewText] = useState<{ x: number; y: number; width: number | null } | null>(null);
  const drawing = useRef(false);
  const { run, ink, shape, redactColor, placement, setPlacement, setTool } = useEditor();

  useEffect(() => {
    setPopover(null);
    setNewText(null);
  }, [tool]);

  const placementSize = (): [number, number] => {
    if (!placement) return [0, 0];
    const maxW = Math.min(220, pageSize[0] * 0.5);
    const ratio = placement.width / placement.height || 1;
    const w = Math.min(maxW, placement.width * 0.75);
    return [w, w / ratio];
  };

  const placeImage = async (rect: Rect) => {
    if (!placement) return;
    const blob = placement.blob;
    setPlacement(null);
    setTool("select");
    await run(() => api.addImage(docId, page, rect, blob), `${placement.label} added`);
  };

  const onPointerDown = (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    if (newText) {
      void flushEdit();
      return;
    }
    if (popover) {
      setPopover(null);
      return;
    }
    const point = toPoint(event);
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drawing.current = true;
    setStart(point);
    setCurrent(point);
    if (tool === "ink") setPath([point]);
  };

  const onPointerMove = (event: ReactPointerEvent) => {
    const point = toPoint(event);
    if (tool === "image") setHover(point);
    if (!drawing.current) return;
    setCurrent(point);
    if (tool === "ink") setPath((p) => (p.length && Math.hypot(p[p.length - 1][0] - point[0], p[p.length - 1][1] - point[1]) < 0.6 / zoom ? p : [...p, point]));
  };

  const reset = () => {
    drawing.current = false;
    setStart(null);
    setCurrent(null);
    setPath([]);
  };

  const onPointerUp = async (event: ReactPointerEvent) => {
    if (!drawing.current || !start) return;
    const end = toPoint(event);
    const rect = normRect(start, end);
    const isClick = rectWidth(rect) < 3 && rectHeight(rect) < 3;
    const points = path;
    reset();
    await finish(start, end, rect, isClick, points);
  };

  const annotStyle = (style: typeof ink) => ({
    color: style.color,
    fill: style.fill,
    opacity: style.opacity,
    width: style.width,
    dashed: style.dashed,
    contents: "",
    author: "",
  });

  const finish = async (a: Point, b: Point, rect: Rect, isClick: boolean, points: Point[]) => {
    switch (tool) {
      case "ink":
        if (points.length > 1) await run(() => api.addAnnotation(docId, { page, kind: "ink", paths: [points], style: annotStyle(ink) }));
        return;
      case "line":
      case "arrow":
        if (!isClick) await run(() => api.addAnnotation(docId, { page, kind: tool, start: a, end: b, style: annotStyle(shape) }));
        return;
      case "rect":
      case "ellipse":
        if (!isClick) await run(() => api.addAnnotation(docId, { page, kind: tool, start: a, end: b, style: annotStyle(shape) }));
        return;
      case "whiteout":
      case "redact":
      case "eraseText": {
        if (isClick) return;
        const mode = tool === "eraseText" ? "text" : tool;
        const color = tool === "whiteout" ? "#ffffff" : redactColor;
        const label = tool === "redact" ? "Area redacted" : tool === "whiteout" ? "Whiteout applied" : "Text erased";
        await run(() => api.redact(docId, page, [rect], mode, color), label);
        return;
      }
      case "image": {
        if (!placement) return;
        if (isClick) {
          const [w, h] = placementSize();
          await placeImage([a[0] - w / 2, a[1] - h / 2, a[0] + w / 2, a[1] + h / 2]);
        } else {
          await placeImage(rect);
        }
        return;
      }
      case "addText":
        setNewText({ x: a[0], y: a[1], width: isClick ? null : Math.max(30, rectWidth(rect)) });
        return;
      case "note":
        setPopover({ kind: "note", point: a });
        return;
      case "textbox":
        setPopover({ kind: "textbox", rect: isClick ? [a[0], a[1], a[0] + 160, a[1] + 40] : rect });
        return;
      case "crop":
        if (!isClick) setPopover({ kind: "crop", rect });
        return;
      case "fieldText":
      case "fieldCheckbox": {
        const fieldRect: Rect = isClick
          ? tool === "fieldCheckbox"
            ? [a[0], a[1], a[0] + 14, a[1] + 14]
            : [a[0], a[1], a[0] + 160, a[1] + 20]
          : rect;
        setPopover({ kind: tool === "fieldText" ? "fieldText" : "fieldCheckbox", rect: fieldRect });
        return;
      }
      default:
    }
  };

  const dragRect = start && current && (RECT_TOOLS.includes(tool) || tool === "addText") ? normRect(start, current) : null;
  const dragClass = tool === "redact" ? " redact" : tool === "whiteout" ? " whiteout" : "";
  const [pw, ph] = placementSize();

  return (
    <div
      className="layer crosshair"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={() => setHover(null)}
    >
      {dragRect && tool !== "rect" && tool !== "ellipse" && <div className={`drag-rect${dragClass}`} style={cssRect(dragRect, zoom)} />}
      <svg className="preview-svg" width={pageSize[0] * zoom} height={pageSize[1] * zoom}>
        <g transform={`scale(${zoom})`}>
          {tool === "ink" && path.length > 1 && (
            <polyline
              points={path.map((p) => p.join(",")).join(" ")}
              fill="none"
              stroke={ink.color}
              strokeOpacity={ink.opacity}
              strokeWidth={ink.width}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
          {dragRect && tool === "rect" && (
            <rect x={dragRect[0]} y={dragRect[1]} width={rectWidth(dragRect)} height={rectHeight(dragRect)}
              fill={shape.fill ?? "none"} stroke={shape.color} strokeWidth={shape.width} strokeDasharray={shape.dashed ? "4 3" : undefined} opacity={shape.opacity} />
          )}
          {dragRect && tool === "ellipse" && (
            <ellipse cx={(dragRect[0] + dragRect[2]) / 2} cy={(dragRect[1] + dragRect[3]) / 2} rx={rectWidth(dragRect) / 2} ry={rectHeight(dragRect) / 2}
              fill={shape.fill ?? "none"} stroke={shape.color} strokeWidth={shape.width} strokeDasharray={shape.dashed ? "4 3" : undefined} opacity={shape.opacity} />
          )}
          {start && current && LINE_TOOLS.includes(tool) && (
            <g stroke={shape.color} strokeWidth={shape.width} opacity={shape.opacity} fill="none" strokeLinecap="round">
              <line x1={start[0]} y1={start[1]} x2={current[0]} y2={current[1]} strokeDasharray={shape.dashed ? "4 3" : undefined} />
              {tool === "arrow" && <path d={arrowHead(start, current, 6 + shape.width * 2)} />}
            </g>
          )}
        </g>
      </svg>
      {tool === "image" && placement && hover && !drawing.current && (
        <img
          className="placement-ghost"
          src={placement.url}
          alt=""
          style={{ left: (hover[0] - pw / 2) * zoom, top: (hover[1] - ph / 2) * zoom, width: pw * zoom, height: ph * zoom }}
        />
      )}
      {popover && <ToolPopover docId={docId} page={page} zoom={zoom} state={popover} onClose={() => setPopover(null)} />}
      {newText && (
        <NewTextEditor docId={docId} page={page} zoom={zoom} x={newText.x} y={newText.y} width={newText.width} onDone={() => setNewText(null)} />
      )}
    </div>
  );
}
