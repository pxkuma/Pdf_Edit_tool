import { Check, Move, TextSelect, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { api } from "../../api/client";
import type { TextBlock } from "../../api/types";
import { registerCommit } from "../../lib/editSession";
import { cssFamily, ensureFace } from "../../lib/fonts";
import { useEditor, type ActiveEdit } from "../../store/editor";
import { beginBlockEdit, blockText, draftChanged, previewFace, reportEdit, styleFromDraft } from "./editHelpers";
import { startDrag } from "./usePointer";

interface SpanEditorProps {
  docId: string;
  edit: ActiveEdit;
  zoom: number;
  block: TextBlock | null;
}

const measureCanvas = document.createElement("canvas");

function measure(text: string, font: string, letterSpacing: number): number {
  const ctx = measureCanvas.getContext("2d");
  if (!ctx) return text.length * 8;
  ctx.font = font;
  return ctx.measureText(text).width + Math.max(0, text.length - 1) * letterSpacing;
}

export function SpanEditor({ docId, edit, zoom, block }: SpanEditorProps) {
  const { span, draft, page } = edit;
  const [text, setText] = useState(span.text);
  const [offset, setOffset] = useState<[number, number]>([0, 0]);
  const [family, setFamily] = useState(cssFamily(span.face, span));
  const inputRef = useRef<HTMLInputElement>(null);
  const state = useRef({ text, offset });
  state.current = { text, offset };
  const run = useEditor((s) => s.run);
  const setActiveEdit = useEditor((s) => s.setActiveEdit);

  const faceId = previewFace(span, draft);
  useEffect(() => {
    let alive = true;
    ensureFace(faceId).then((css) => alive && setFamily(`${css}, ${span.serif ? "serif" : "sans-serif"}`));
    return () => {
      alive = false;
    };
  }, [faceId, span.serif]);

  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.focus();
    input.select();
  }, [span.id]);

  const commit = useCallback(async () => {
    registerCommit(null);
    const current = useEditor.getState().activeEdit;
    const latest = current && current.span.id === span.id ? current.draft : draft;
    const { text: value, offset: [dx, dy] } = state.current;
    setActiveEdit(null);
    if (value === span.text && !dx && !dy && !draftChanged(span, latest) && latest.ocrMode !== "hidden") return;
    const report = await run(() =>
      api.editSpan(docId, {
        page,
        bbox: span.bbox,
        origin: span.origin,
        original_text: span.text,
        text: value,
        style: styleFromDraft(span, latest),
        dx,
        dy,
        fit_width: latest.fitWidth,
        reflow: latest.reflow,
        ocr_mode: latest.ocrMode,
      }),
    );
    reportEdit(report);
  }, [docId, page, span, draft, run, setActiveEdit]);

  useEffect(() => {
    registerCommit(commit);
    return () => registerCommit(null);
  }, [commit]);

  const cancel = () => {
    registerCommit(null);
    setActiveEdit(null);
  };

  const toTextBox = () => {
    if (!block) return;
    // Carry over what was typed so far into the block's text.
    const typed = state.current.text;
    const base = blockText(block);
    const text = typed !== span.text && base.includes(span.text) ? base.replace(span.text, typed) : base;
    const next = beginBlockEdit(page, block, text);
    registerCommit(null);
    setActiveEdit(next);
  };

  const scale = draft.size / span.size;
  const height = (span.bbox[3] - span.bbox[1]) * scale * zoom;
  const fontSize = draft.size * zoom;
  const letterSpacing = (draft.charSpacing ?? 0) * zoom;
  const weight = draft.bold ? 700 : 400;
  const fontCss = `${draft.italic ? "italic " : ""}${weight} ${fontSize}px ${family}`;
  const textWidth = measure(text || " ", fontCss, letterSpacing);
  const originalWidth = (span.bbox[2] - span.bbox[0]) * zoom;
  const scaleX = draft.fitWidth ? originalWidth / Math.max(textWidth, 1) : draft.hscale / 100;
  const left = (span.bbox[0] + offset[0]) * zoom;
  const top = (span.bbox[1] + offset[1]) * zoom;
  const decorations = [draft.underline && "underline", draft.strike && "line-through"].filter(Boolean).join(" ");

  const style: CSSProperties = {
    left,
    top,
    width: Math.max(textWidth + 6, 24),
    height,
    fontStyle: draft.italic ? "italic" : "normal",
    fontWeight: weight,
    fontSize,
    fontFamily: family,
    lineHeight: `${height}px`,
    letterSpacing,
    color: draft.color,
    opacity: Math.max(draft.opacity, 0.35),
    textDecoration: decorations || undefined,
    transform: Math.abs(scaleX - 1) > 0.001 ? `scaleX(${scaleX})` : undefined,
    transformOrigin: "left center",
  };

  const onMoveStart = (event: ReactPointerEvent) => {
    const start = offset;
    startDrag(
      event,
      (dx, dy) => setOffset([start[0] + dx / zoom, start[1] + dy / zoom]),
      () => inputRef.current?.focus(),
    );
  };

  return (
    <>
      <div className="edit-chip" style={{ left, top }} onPointerDown={(e) => e.stopPropagation()}>
        <span className="drag-handle" title="Drag to move" onPointerDown={onMoveStart}>
          <Move size={14} />
        </span>
        <button className="btn small primary" onClick={() => void commit()} title="Apply (Enter)">
          <Check size={14} /> Apply
        </button>
        <button className="icon-btn small" onClick={cancel} title="Cancel (Esc)">
          <X size={14} />
        </button>
        {block && !span.ocr && (
          <button className="icon-btn small" onClick={toTextBox} title="Edit as a text box (move, resize, wrap lines)">
            <TextSelect size={14} />
          </button>
        )}
      </div>
      <input
        ref={inputRef}
        className="span-editor"
        value={text}
        spellCheck={false}
        style={style}
        onChange={(e) => setText(e.target.value)}
        onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Enter") void commit();
          if (e.key === "Escape") cancel();
        }}
        aria-label="Edit text"
      />
    </>
  );
}
