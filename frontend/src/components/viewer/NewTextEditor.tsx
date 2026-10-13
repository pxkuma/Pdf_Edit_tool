import { Check, MoveHorizontal, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Rect } from "../../api/types";
import { api } from "../../api/client";
import { registerCommit } from "../../lib/editSession";
import { cssFamily, ensureFace, findFace, useFonts, variantOf } from "../../lib/fonts";
import { NUDGE, SNAP_PX, snapBox, snapEdge, snapTargets, type Guides } from "../../lib/snap";
import { naturalWidth, scaleBox, widenBox, type HBox } from "../../lib/textBox";
import { useEditor } from "../../store/editor";
import { reportEdit } from "./editHelpers";
import { SnapGuides } from "./SnapGuides";
import { TextBoxFrame, type BoxGesture } from "./TextBoxFrame";

interface NewTextEditorProps {
  docId: string;
  page: number;
  zoom: number;
  x: number;
  y: number;
  width: number | null; // null = auto width (no wrapping except at line breaks)
  snapRects: Rect[];
  pageSize: [number, number];
  onDone: () => void;
}

const NO_WRAP = 20000;
const round2 = (value: number) => Math.round(value * 100) / 100;

export function NewTextEditor({ docId, page, zoom, x, y, width: initialWidth, snapRects, pageSize, onDone }: NewTextEditorProps) {
  const style = useEditor((s) => s.newText);
  const patchNewText = useEditor((s) => s.patchNewText);
  const run = useEditor((s) => s.run);
  const { families, defaultFace } = useFonts();
  const [text, setText] = useState(() => useEditor.getState().textPreset ?? "");
  const [pos, setPos] = useState({ x, y });
  const [width, setWidth] = useState<number | null>(initialWidth);
  const [family, setFamily] = useState("sans-serif");
  const [guides, setGuides] = useState<Guides>({});
  const targets = useMemo(
    () => snapTargets(snapRects, { width: pageSize[0], height: pageSize[1] }),
    [snapRects, pageSize[0], pageSize[1]],
  );
  const ref = useRef<HTMLTextAreaElement>(null);

  const baseFace = style.faceId ?? defaultFace;
  const found = findFace(families, baseFace);
  const faceId = found ? variantOf(found.family, style.bold, style.italic).id : baseFace;

  useEffect(() => {
    let alive = true;
    ensureFace(faceId).then((css) => alive && setFamily(`${css}, ${found?.family.serif ? "serif" : "sans-serif"}`));
    return () => {
      alive = false;
    };
  }, [faceId, found?.family.serif]);

  useLayoutEffect(() => {
    ref.current?.focus();
  }, []);

  const fontCss = `${style.italic ? "italic " : ""}${style.bold ? 700 : 400} ${style.size}px ${family}`;
  const box: HBox =
    width !== null
      ? { x: pos.x, width }
      : { x: pos.x, width: Math.max(naturalWidth(text || "Type here…", fontCss) + 4, style.size * 2) };
  const state = useRef({ text, pos, width, box });
  state.current = { text, pos, width, box };

  useLayoutEffect(() => {
    const area = ref.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight}px`;
  });

  const commit = useCallback(async () => {
    registerCommit(null);
    onDone();
    const current = state.current;
    if (!current.text.trim()) return;
    const latest = useEditor.getState().newText;
    const report = await run(() =>
      api.addText(docId, {
        page,
        x: round2(current.pos.x),
        y: round2(current.pos.y),
        text: current.text,
        style: {
          font: latest.faceId ? `face:${latest.faceId}` : "",
          size: latest.size,
          color: latest.color,
          bold: latest.bold,
          italic: latest.italic,
          underline: latest.underline,
          strike: latest.strike,
          opacity: latest.opacity,
        },
        width: round2(current.box.width),
        max_width: current.width === null ? NO_WRAP : null,
        align: latest.align,
        line_height: latest.lineHeight,
        rotation: 0,
      }),
    );
    reportEdit(report);
  }, [docId, page, run, onDone]);

  useEffect(() => {
    registerCommit(commit);
    return () => registerCommit(null);
  }, [commit]);

  const cancel = () => {
    registerCommit(null);
    onDone();
  };

  const onGesture = (gesture: BoxGesture) => {
    const start = state.current;
    const startSize = useEditor.getState().newText.size;
    const height = (ref.current?.offsetHeight ?? 0) / zoom;
    const threshold = SNAP_PX / zoom;
    return (dxPx: number, dyPx: number, free: boolean) => {
      const dx = dxPx / zoom;
      const dy = dyPx / zoom;
      if (gesture === "move") {
        const proposed = { x: start.pos.x + dx, y: start.pos.y + dy, width: start.box.width, height };
        const snapped = free ? { ...proposed, guides: {} } : snapBox(proposed, targets, threshold);
        setGuides(snapped.guides);
        setPos({ x: snapped.x, y: snapped.y });
      } else if (gesture === "e" || gesture === "w") {
        const next = widenBox(start.box, gesture, dx);
        const edge = gesture === "e" ? next.x + next.width : next.x;
        const snapped = free ? { value: edge, guide: undefined } : snapEdge(edge, targets.xs, threshold);
        const fixed = widenBox(next, gesture, snapped.value - edge);
        setGuides({ x: snapped.guide });
        setPos({ x: fixed.x, y: start.pos.y });
        setWidth(fixed.width);
      } else {
        const scaled = scaleBox(start.box, startSize, gesture, dx);
        patchNewText({ size: scaled.size });
        if (start.width !== null) {
          setPos({ x: scaled.box.x, y: start.pos.y });
          setWidth(scaled.box.width);
        }
      }
    };
  };

  const setAutoWidth = (auto: boolean) => {
    setWidth(auto ? null : state.current.box.width);
    ref.current?.focus();
  };

  const left = box.x * zoom;
  const top = pos.y * zoom;
  const auto = width === null;
  return (
    <>
      <SnapGuides guides={guides} zoom={zoom} />
      <div className="edit-chip" style={{ left, top }} onPointerDown={(e) => e.stopPropagation()}>
        <button
          className={`icon-btn small${auto ? " active" : ""}`}
          onClick={() => setAutoWidth(!auto)}
          title={auto ? "Auto width: one line per line you type. Click to fix the width." : "Fixed width: text wraps inside the box. Click for auto width."}
          aria-pressed={auto}
        >
          <MoveHorizontal size={14} />
        </button>
        <button className="btn small primary" onClick={() => void commit()} title="Add text (Ctrl+Enter)">
          <Check size={14} /> Add
        </button>
        <button className="icon-btn small" onClick={cancel} title="Cancel (Esc)">
          <X size={14} />
        </button>
      </div>
      <TextBoxFrame
        left={left}
        top={top}
        width={box.width * zoom}
        autoWidth={auto}
        onGesture={onGesture}
        onGestureEnd={() => {
          setGuides({});
          ref.current?.focus();
        }}
        onAutoWidth={() => setAutoWidth(true)}
      >
        <textarea
          ref={ref}
          className="text-box-editor"
          value={text}
          rows={1}
          placeholder="Type here…"
          spellCheck={false}
          wrap={auto ? "off" : "soft"}
          style={{
            fontFamily: family || cssFamily(faceId),
            fontSize: style.size * zoom,
            fontWeight: style.bold ? 700 : 400,
            fontStyle: style.italic ? "italic" : "normal",
            lineHeight: style.lineHeight,
            color: style.color,
            opacity: Math.max(style.opacity, 0.35),
            textAlign: style.align,
            textDecoration: [style.underline && "underline", style.strike && "line-through"].filter(Boolean).join(" ") || undefined,
          }}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void commit();
            if (e.key === "Escape") cancel();
            const arrow = NUDGE[e.key];
            if (arrow && e.altKey) {
              e.preventDefault();
              const step = e.shiftKey ? 10 : 1;
              setPos((p) => ({ x: p.x + arrow[0] * step, y: p.y + arrow[1] * step }));
            }
          }}
          aria-label="New text"
        />
      </TextBoxFrame>
    </>
  );
}
