import { Check, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { registerCommit } from "../../lib/editSession";
import { cssFamily, ensureFace } from "../../lib/fonts";
import { useEditor, type ActiveEdit } from "../../store/editor";
import { draftChanged, previewFace, reportEdit, styleFromDraft } from "./editHelpers";

interface BlockEditorProps {
  docId: string;
  edit: ActiveEdit;
  zoom: number;
}

export function BlockEditor({ docId, edit, zoom }: BlockEditorProps) {
  const { span, draft, page } = edit;
  const bbox = edit.blockBbox ?? span.bbox;
  const initial = edit.blockText ?? span.text;
  const [text, setText] = useState(initial);
  const [family, setFamily] = useState(cssFamily(span.face, span));
  const ref = useRef<HTMLTextAreaElement>(null);
  const textRef = useRef(text);
  textRef.current = text;
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
    ref.current?.focus();
  }, []);

  useLayoutEffect(() => {
    const area = ref.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${Math.max(area.scrollHeight, (bbox[3] - bbox[1]) * zoom)}px`;
  }, [text, zoom, bbox, draft.size, family]);

  const commit = useCallback(async () => {
    registerCommit(null);
    const latest = useEditor.getState().activeEdit ?? edit;
    setActiveEdit(null);
    const value = textRef.current;
    if (value === initial && latest.align === "left" && !draftChanged(span, latest.draft)) return;
    const report = await run(() =>
      api.editBlock(docId, { page, bbox, text: value, style: styleFromDraft(span, latest.draft), align: latest.align }),
    );
    reportEdit(report);
  }, [docId, page, bbox, span, initial, edit, run, setActiveEdit]);

  useEffect(() => {
    registerCommit(commit);
    return () => registerCommit(null);
  }, [commit]);

  const cancel = () => {
    registerCommit(null);
    setActiveEdit(null);
  };

  const left = bbox[0] * zoom;
  const top = bbox[1] * zoom;
  const width = (bbox[2] - bbox[0]) * zoom;
  const lineHeight = draft.size * 1.18 * zoom;

  return (
    <>
      <div className="edit-chip" style={{ left, top }} onPointerDown={(e) => e.stopPropagation()}>
        <span className="badge" style={{ marginRight: 4 }}>Paragraph</span>
        <button className="btn small primary" onClick={() => void commit()} title="Apply (Ctrl+Enter)">
          <Check size={14} /> Apply
        </button>
        <button className="icon-btn small" onClick={cancel} title="Cancel (Esc)">
          <X size={14} />
        </button>
      </div>
      <textarea
        ref={ref}
        className="block-editor"
        value={text}
        spellCheck={false}
        style={{
          left,
          top,
          width: width + 4,
          fontFamily: family,
          fontSize: draft.size * zoom,
          fontWeight: draft.bold ? 700 : 400,
          fontStyle: draft.italic ? "italic" : "normal",
          lineHeight: `${lineHeight}px`,
          color: draft.color,
          textAlign: edit.align,
          textDecoration: [draft.underline && "underline", draft.strike && "line-through"].filter(Boolean).join(" ") || undefined,
        }}
        onChange={(e) => setText(e.target.value)}
        onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void commit();
          if (e.key === "Escape") cancel();
        }}
        aria-label="Edit paragraph"
      />
    </>
  );
}
