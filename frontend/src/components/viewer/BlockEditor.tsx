import { Check, MoveHorizontal, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type { Rect } from "../../api/types";
import { registerCommit } from "../../lib/editSession";
import { cssFamily, ensureFace } from "../../lib/fonts";
import { boxGrowth, pushConflicts, selectPush, type PushCandidate } from "../../lib/push";
import { autoBox, freeSpan, naturalWidth, scaleBox, widenBox, type HBox } from "../../lib/textBox";
import { AUTO_BOX, DEFAULT_PUSH, useEditor, type ActiveEdit } from "../../store/editor";
import { draftChanged, previewFace, reportEdit, styleFromDraft } from "./editHelpers";
import { PushPreview } from "./PushPreview";
import { TextBoxFrame, type BoxGesture } from "./TextBoxFrame";

interface BlockEditorProps {
  docId: string;
  edit: ActiveEdit;
  zoom: number;
  obstacles: { id: string; bbox: Rect }[]; // other text on the page
  candidates: PushCandidate[]; // what could move below the box
  renderSrc: string | null;
  pageSize: [number, number];
}

interface BoxLayout {
  box: HBox;
  maxWidth: number; // where lines wrap
  auto: boolean;
}

const round2 = (value: number) => Math.round(value * 100) / 100;

/** Edit a whole text block as a movable, resizable text box. */
export function BlockEditor({ docId, edit, zoom, obstacles, candidates, renderSrc, pageSize }: BlockEditorProps) {
  const pageWidth = pageSize[0];
  const { span, draft, page } = edit;
  const original = edit.blockBbox ?? span.bbox;
  const geometry = edit.box ?? AUTO_BOX;
  const initial = edit.blockText ?? span.text;
  const [text, setText] = useState(initial);
  const [family, setFamily] = useState(cssFamily(span.face, span));
  const [rows, setRows] = useState(edit.lineCount ?? 1);
  const ref = useRef<HTMLTextAreaElement>(null);
  const textRef = useRef(text);
  textRef.current = text;
  const run = useEditor((s) => s.run);
  const setActiveEdit = useEditor((s) => s.setActiveEdit);
  const patchEdit = useEditor((s) => s.patchEdit);

  const faceId = previewFace(span, draft);
  useEffect(() => {
    let alive = true;
    ensureFace(faceId).then((css) => alive && setFamily(`${css}, ${span.serif ? "serif" : "sans-serif"}`));
    return () => {
      alive = false;
    };
  }, [faceId, span.serif]);

  useLayoutEffect(() => {
    const area = ref.current;
    if (!area) return;
    area.focus();
    area.setSelectionRange(area.value.length, area.value.length);
  }, []);

  const fontCss = `${draft.italic ? "italic " : ""}${draft.bold ? 700 : 400} ${draft.size}px ${family}`;
  const moved: Rect = [original[0] + geometry.dx, original[1] + geometry.dy, original[2] + geometry.dx, original[3] + geometry.dy];
  const layout: BoxLayout = (() => {
    if (geometry.width !== null) {
      return { box: { x: moved[0], width: geometry.width }, maxWidth: geometry.width, auto: false };
    }
    const free = freeSpan(moved, obstacles, null, { width: pageWidth });
    // A little slack: browser and PDF metrics differ slightly.
    const natural = naturalWidth(text, fontCss) + Math.max(2, draft.size * 0.25);
    return {
      box: autoBox(moved, natural, free, edit.align),
      maxWidth: autoBox(moved, Infinity, free, edit.align).width,
      auto: true,
    };
  })();
  const layoutRef = useRef(layout);
  layoutRef.current = layout;

  const scale = draft.size / span.size;
  const step = edit.lineHeight ? draft.size * edit.lineHeight : (edit.lineStep ?? span.size * 1.2) * scale;
  const minHeight = (original[3] - original[1]) * scale * zoom;

  // Fit the height to the text after every render (width, font and size all affect it).
  useLayoutEffect(() => {
    const area = ref.current;
    if (!area) return;
    area.style.height = "auto";
    const content = area.scrollHeight;
    area.style.height = `${Math.max(content, minHeight)}px`;
    setRows(Math.max(1, Math.round(content / (step * zoom))));
  });

  // Content below: how far it moves and what moves (previewed live, sent on apply).
  const push = edit.push ?? DEFAULT_PUSH;
  const growth = boxGrowth({
    rows,
    lines: edit.lineCount ?? 1,
    step,
    originalStep: edit.lineStep ?? span.size * 1.2,
    size: draft.size,
    originalSize: span.size,
  });
  const pushDy = push.enabled ? Math.round(((push.follow ? growth : Math.max(0, growth)) + push.extra) * 100) / 100 : 0;
  const columnX: [number, number] = [Math.min(original[0], layout.box.x), Math.max(original[2], layout.box.x + layout.box.width)];
  const selection = useMemo(
    () => selectPush(candidates, original, columnX, push, { width: pageSize[0], height: pageSize[1] }),
    [candidates, original, columnX[0], columnX[1], push.scope, push.overrides, pageSize[0], pageSize[1]],
  );
  const pushRef = useRef({ dy: pushDy, items: selection.moving });
  pushRef.current = { dy: pushDy, items: selection.moving };
  const offPage = selection.moving.filter((m) => m.bbox[3] + pushDy > pageSize[1]).length;
  const conflicts = useMemo(() => pushConflicts(selection.moving, selection.kept, pushDy), [selection, pushDy]);
  const info =
    Math.abs(pushDy) < 0.05
      ? { count: 0, dy: 0, offPage: 0, conflicts: 0 }
      : { count: selection.moving.length, dy: pushDy, offPage, conflicts: conflicts.length };
  useEffect(() => {
    const current = useEditor.getState().activeEdit?.pushInfo;
    const changed = !current || (Object.keys(info) as (keyof typeof info)[]).some((k) => current[k] !== info[k]);
    if (changed) {
      patchEdit({ pushInfo: info });
    }
  });

  const pushPayload = () => {
    const { dy, items } = pushRef.current;
    if (Math.abs(dy) < 0.05 || !items.length) return null;
    return { dy, items: items.map((i) => ({ kind: i.kind, bbox: i.bbox, xref: i.xref ?? 0 })) };
  };

  const commit = useCallback(async () => {
    registerCommit(null);
    const latest = useEditor.getState().activeEdit ?? edit;
    const box = latest.box ?? AUTO_BOX;
    const { box: hbox, maxWidth, auto } = layoutRef.current;
    setActiveEdit(null);
    const value = textRef.current;
    const geometryChanged = box.dx !== 0 || box.dy !== 0 || box.width !== null || pushPayload() !== null;
    const unchanged = value === initial && latest.align === "left" && !latest.lineHeight && !geometryChanged;
    if (unchanged && !draftChanged(span, latest.draft)) return;
    const report = await run(() =>
      api.editBlock(docId, {
        page,
        bbox: original,
        text: value,
        style: styleFromDraft(span, latest.draft),
        align: latest.align,
        line_height: latest.lineHeight ?? null,
        width: round2(hbox.width),
        max_width: auto ? round2(maxWidth) : null,
        dx: round2(hbox.x - original[0]),
        dy: round2(box.dy),
        push: pushPayload(),
      }),
    );
    reportEdit(report);
  }, [docId, page, original, span, initial, edit, run, setActiveEdit]);

  useEffect(() => {
    registerCommit(commit);
    return () => registerCommit(null);
  }, [commit]);

  const cancel = () => {
    registerCommit(null);
    setActiveEdit(null);
  };

  const onGesture = (gesture: BoxGesture) => {
    const start = useEditor.getState().activeEdit ?? edit;
    const startBox = start.box ?? AUTO_BOX;
    const startLayout = layoutRef.current.box;
    const startSize = start.draft.size;
    return (dxPx: number, dyPx: number) => {
      const dx = dxPx / zoom;
      const dy = dyPx / zoom;
      if (gesture === "move") {
        patchEdit({ box: { ...startBox, dx: startBox.dx + dx, dy: startBox.dy + dy } });
      } else if (gesture === "e" || gesture === "w") {
        const next = widenBox(startLayout, gesture, dx);
        patchEdit({ box: { dx: next.x - original[0], dy: startBox.dy, width: next.width } });
      } else {
        const scaled = scaleBox(startLayout, startSize, gesture, dx);
        const current = useEditor.getState().activeEdit;
        if (!current) return;
        const box = startBox.width === null ? startBox : { dx: scaled.box.x - original[0], dy: startBox.dy, width: scaled.box.width };
        patchEdit({ draft: { ...current.draft, size: scaled.size }, box });
      }
    };
  };

  const setAutoWidth = (auto: boolean) => {
    const { box } = layoutRef.current;
    patchEdit({ box: auto ? { ...geometry, width: null } : { dx: box.x - original[0], dy: geometry.dy, width: box.width } });
    ref.current?.focus();
  };

  const togglePush = (item: PushCandidate, move: boolean) => {
    const current = useEditor.getState().activeEdit?.push ?? DEFAULT_PUSH;
    patchEdit({ push: { ...current, overrides: { ...current.overrides, [item.key]: move } } });
    ref.current?.focus();
  };

  const left = layout.box.x * zoom;
  const top = moved[1] * zoom;

  return (
    <>
      <PushPreview
        selection={selection}
        conflicts={conflicts}
        dy={pushDy}
        zoom={zoom}
        renderSrc={renderSrc}
        pageSize={pageSize}
        onToggle={togglePush}
      />
      <div className="edit-chip" style={{ left, top }} onPointerDown={(e) => e.stopPropagation()}>
        <span className="chip-label">Text box</span>
        <button
          className={`icon-btn small${layout.auto ? " active" : ""}`}
          onClick={() => setAutoWidth(!layout.auto)}
          title={layout.auto ? "Auto width: grows into free space, then wraps. Click to fix the width." : "Fixed width: text wraps inside the box. Click for auto width."}
          aria-pressed={layout.auto}
        >
          <MoveHorizontal size={14} />
        </button>
        <button className="btn small primary" onClick={() => void commit()} title="Apply (Ctrl+Enter)">
          <Check size={14} /> Apply
        </button>
        <button className="icon-btn small" onClick={cancel} title="Cancel (Esc)">
          <X size={14} />
        </button>
      </div>
      <TextBoxFrame
        left={left}
        top={top}
        width={layout.box.width * zoom}
        autoWidth={layout.auto}
        onGesture={onGesture}
        onGestureEnd={() => ref.current?.focus()}
        onAutoWidth={() => setAutoWidth(true)}
      >
        <textarea
          ref={ref}
          className="block-editor"
          value={text}
          rows={1}
          spellCheck={false}
          wrap="soft"
          style={{
            fontFamily: family,
            fontSize: draft.size * zoom,
            fontWeight: draft.bold ? 700 : 400,
            fontStyle: draft.italic ? "italic" : "normal",
            lineHeight: `${step * zoom}px`,
            color: draft.color,
            opacity: Math.max(draft.opacity, 0.35),
            textAlign: edit.align,
            textDecoration: [draft.underline && "underline", draft.strike && "line-through"].filter(Boolean).join(" ") || undefined,
          }}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void commit();
            if (e.key === "Escape") cancel();
          }}
          aria-label="Edit text box"
        />
      </TextBoxFrame>
    </>
  );
}
