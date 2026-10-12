import { Check, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { registerCommit } from "../../lib/editSession";
import { cssFamily, ensureFace, findFace, useFonts, variantOf } from "../../lib/fonts";
import { useEditor } from "../../store/editor";
import { reportEdit } from "./editHelpers";

interface NewTextEditorProps {
  docId: string;
  page: number;
  zoom: number;
  x: number;
  y: number;
  width: number | null;
  onDone: () => void;
}

export function NewTextEditor({ docId, page, zoom, x, y, width, onDone }: NewTextEditorProps) {
  const style = useEditor((s) => s.newText);
  const run = useEditor((s) => s.run);
  const { families, defaultFace } = useFonts();
  const [text, setText] = useState(() => useEditor.getState().textPreset ?? "");
  const [family, setFamily] = useState("sans-serif");
  const ref = useRef<HTMLTextAreaElement>(null);
  const textRef = useRef(text);
  textRef.current = text;

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

  useLayoutEffect(() => {
    const area = ref.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight}px`;
    if (!width) {
      area.style.width = "auto";
      area.style.width = `${Math.max(area.scrollWidth + 4, 40)}px`;
    }
  }, [text, zoom, style, family, width]);

  const commit = useCallback(async () => {
    registerCommit(null);
    onDone();
    const value = textRef.current;
    if (!value.trim()) return;
    const latest = useEditor.getState().newText;
    const report = await run(() =>
      api.addText(docId, {
        page,
        x,
        y,
        text: value,
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
        width,
        align: latest.align,
        line_height: latest.lineHeight,
        rotation: 0,
      }),
    );
    reportEdit(report);
  }, [docId, page, x, y, width, run, onDone]);

  useEffect(() => {
    registerCommit(commit);
    return () => registerCommit(null);
  }, [commit]);

  const cancel = () => {
    registerCommit(null);
    onDone();
  };

  const left = x * zoom;
  const top = y * zoom;
  return (
    <>
      <div className="edit-chip" style={{ left, top }} onPointerDown={(e) => e.stopPropagation()}>
        <button className="btn small primary" onClick={() => void commit()} title="Add text (Ctrl+Enter)">
          <Check size={14} /> Add
        </button>
        <button className="icon-btn small" onClick={cancel} title="Cancel (Esc)">
          <X size={14} />
        </button>
      </div>
      <textarea
        ref={ref}
        className="text-box-editor"
        value={text}
        rows={1}
        placeholder="Type here…"
        spellCheck={false}
        wrap={width ? "soft" : "off"}
        style={{
          left,
          top,
          width: width ? width * zoom : undefined,
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
        onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void commit();
          if (e.key === "Escape") cancel();
        }}
        aria-label="New text"
      />
    </>
  );
}
