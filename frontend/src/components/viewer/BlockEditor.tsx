import { Check, MoveHorizontal, Pencil, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { api } from "../../api/client";
import type { Point, Rect } from "../../api/types";
import { registerCommit } from "../../lib/editSession";
import { cssFamily, ensureFace } from "../../lib/fonts";
import type { PushCandidate } from "../../lib/push";
import { NUDGE, SNAP_PX, snapBox, snapEdge, snapTargets, type Guides } from "../../lib/snap";
import { autoBox, naturalWidth, scaleBox, widenBox, type HBox } from "../../lib/textBox";
import { AUTO_BOX, useEditor, type ActiveEdit } from "../../store/editor";
import { beginSpanEdit, draftChanged, previewFace, reportEdit, styleFromDraft } from "./editHelpers";
import { PushPreview } from "./PushPreview";
import { SnapGuides } from "./SnapGuides";
import { TextBoxFrame, type BoxGesture } from "./TextBoxFrame";
import { useBoxPush } from "./useBoxPush";

interface BlockEditorProps {
  docId: string;
  edit: ActiveEdit;
  zoom: number;
  obstacles: { id: string; bbox: Rect }[]; // other text on the page (snapping)
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
const DOUBLE_PRESS_MS = 450;

/**
 * A text box, Canva-style. Selected: drag to move, side handles set the width,
 * corners scale the text, arrows nudge, Delete removes, Enter or a double-click
 * starts typing. Moving alone keeps the text exactly as it is (mixed styles too).
 */
export function BlockEditor({ docId, edit, zoom, obstacles, candidates, renderSrc, pageSize }: BlockEditorProps) {
  const { span, draft, page } = edit;
  const original = edit.blockBbox ?? span.bbox;
  const geometry = edit.box ?? AUTO_BOX;
  const initial = edit.blockText ?? span.text;
  const typing = edit.typing ?? true;
  const [text, setText] = useState(initial);
  const [family, setFamily] = useState(cssFamily(span.face, span));
  const [rows, setRows] = useState(edit.lineCount ?? 1);
  const [guides, setGuides] = useState<Guides>({});
  const targets = useMemo(
    () => snapTargets(obstacles.map((o) => o.bbox), { width: pageSize[0], height: pageSize[1] }),
    [obstacles, pageSize[0], pageSize[1]],
  );
  const ref = useRef<HTMLTextAreaElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const lastPress = useRef(edit.pressedAt ?? 0);
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

  // Typing focuses the text (caret at the end); selected focuses the frame for keys.
  useLayoutEffect(() => {
    if (typing) {
      const area = ref.current;
      area?.focus();
      area?.setSelectionRange(area.value.length, area.value.length);
    } else {
      frameRef.current?.focus({ preventScroll: true });
    }
  }, [typing]);

  const restyled = draftChanged(span, draft) || edit.align !== "left" || !!edit.lineHeight || geometry.width !== null;
  // Untouched text is shown as its real pixels; once retyped or restyled, as live text.
  const pixels = !typing && text === initial && !restyled;

  const fontCss = `${draft.italic ? "italic " : ""}${draft.bold ? 700 : 400} ${draft.size}px ${family}`;
  const moved: Rect = [original[0] + geometry.dx, original[1] + geometry.dy, original[2] + geometry.dx, original[3] + geometry.dy];
  const layout: BoxLayout = (() => {
    if (geometry.width !== null) {
      return { box: { x: moved[0], width: geometry.width }, maxWidth: geometry.width, auto: false };
    }
    if (pixels) return { box: { x: moved[0], width: original[2] - original[0] }, maxWidth: pageSize[0], auto: true };
    // No limits: the box may grow up to the page edge (snapping guides help align it).
    const free = { left: 0, right: pageSize[0] };
    const natural = naturalWidth(text, fontCss) + Math.max(2, draft.size * 0.25); // metric slack
    return { box: autoBox(moved, natural, free, edit.align), maxWidth: autoBox(moved, Infinity, free, edit.align).width, auto: true };
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
    if (!pixels) setRows(Math.max(1, Math.round(content / (step * zoom))));
  });

  const columnX: [number, number] = [Math.min(original[0], layout.box.x), Math.max(original[2], layout.box.x + layout.box.width)];
  const push = useBoxPush({ edit, original, columnX, rows: pixels ? edit.lineCount ?? 1 : rows, step, candidates, pageSize });

  const boxInfo = { x: round2(layout.box.x), y: round2(moved[1]), width: round2(layout.box.width), auto: layout.auto };
  useEffect(() => {
    const current = useEditor.getState().activeEdit?.boxInfo;
    if (!current || (Object.keys(boxInfo) as (keyof typeof boxInfo)[]).some((k) => current[k] !== boxInfo[k])) {
      patchEdit({ boxInfo });
    }
  });

  const commit = useCallback(async () => {
    registerCommit(null);
    const latest = useEditor.getState().activeEdit ?? edit;
    const box = latest.box ?? AUTO_BOX;
    const { box: hbox, maxWidth, auto } = layoutRef.current;
    setActiveEdit(null);
    const value = textRef.current;
    const pushed = push.payload();
    const changedStyle = draftChanged(span, latest.draft) || latest.align !== "left" || !!latest.lineHeight || box.width !== null;
    if (value === initial && !changedStyle && !pushed) {
      if (!box.dx && !box.dy) return;
      // Only moved: move the lines exactly as they are (fonts, mixed styles, decorations).
      const to: Rect = [original[0] + box.dx, original[1] + box.dy, original[2] + box.dx, original[3] + box.dy];
      const items = (latest.boxLines ?? [original]).map((bbox) => ({ kind: "text", bbox }));
      await run(() => api.transformObjects(docId, { page, items, from_rect: original, to_rect: to }));
      return;
    }
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
        push: pushed,
      }),
    );
    reportEdit(report);
  }, [docId, page, original, span, initial, edit, run, setActiveEdit, push]);

  useEffect(() => {
    registerCommit(commit);
    return () => registerCommit(null);
  }, [commit]);

  const cancel = () => {
    registerCommit(null);
    setActiveEdit(null);
  };

  const remove = async () => {
    registerCommit(null);
    setActiveEdit(null);
    const items = (edit.boxLines ?? [original]).map((bbox) => ({ kind: "text", bbox }));
    await run(() => api.deleteObjects(docId, { page, items }), "Text box deleted");
  };

  /** Start typing; a box with mixed styles is edited run by run (keeps each run's style). */
  const startTyping = (at?: Point) => {
    if (edit.uniform !== false) {
      patchEdit({ typing: true });
      return;
    }
    const spans = edit.boxSpans ?? [span];
    const target = (at && spans.find((s) => at[0] >= s.bbox[0] && at[0] <= s.bbox[2] && at[1] >= s.bbox[1] && at[1] <= s.bbox[3])) ?? span;
    if (geometry.dx || geometry.dy) {
      void commit(); // apply the move first; the runs are re-read afterwards
      return;
    }
    registerCommit(null);
    setActiveEdit(beginSpanEdit(page, target));
  };

  const onGesture = (gesture: BoxGesture, clientX?: number, clientY?: number) => {
    if (gesture === "move" && !typing && clientX !== undefined) {
      const now = Date.now();
      const double = now - lastPress.current < DOUBLE_PRESS_MS;
      lastPress.current = now;
      if (double) {
        const rect = frameRef.current?.parentElement?.getBoundingClientRect();
        startTyping(rect ? [(clientX - rect.left) / zoom, (clientY! - rect.top) / zoom] : undefined);
      }
    }
    const start = useEditor.getState().activeEdit ?? edit;
    const startBox = start.box ?? AUTO_BOX;
    const startLayout = layoutRef.current.box;
    const startSize = start.draft.size;
    const startTop = original[1] + startBox.dy;
    const height = (frameRef.current?.offsetHeight ?? 0) / zoom;
    const threshold = SNAP_PX / zoom;
    return (dxPx: number, dyPx: number, free: boolean) => {
      const dx = dxPx / zoom;
      const dy = dyPx / zoom;
      if (gesture === "move") {
        const proposed = { x: startLayout.x + dx, y: startTop + dy, width: startLayout.width, height };
        const snapped = free ? { ...proposed, guides: {} } : snapBox(proposed, targets, threshold);
        setGuides(snapped.guides);
        patchEdit({ box: { ...startBox, dx: startBox.dx + snapped.x - startLayout.x, dy: startBox.dy + snapped.y - startTop } });
      } else if (gesture === "e" || gesture === "w") {
        const next = widenBox(startLayout, gesture, dx);
        const edge = gesture === "e" ? next.x + next.width : next.x;
        const snapped = free ? { value: edge, guide: undefined } : snapEdge(edge, targets.xs, threshold);
        const fixed = widenBox(next, gesture, snapped.value - edge);
        setGuides({ x: snapped.guide });
        patchEdit({ box: { dx: fixed.x - original[0], dy: startBox.dy, width: fixed.width } });
      } else {
        const scaled = scaleBox(startLayout, startSize, gesture, dx);
        const current = useEditor.getState().activeEdit;
        if (!current) return;
        const box = startBox.width === null ? startBox : { dx: scaled.box.x - original[0], dy: startBox.dy, width: scaled.box.width };
        patchEdit({ draft: { ...current.draft, size: scaled.size }, box });
      }
    };
  };

  const nudge = (dx: number, dy: number) => {
    const current = useEditor.getState().activeEdit?.box ?? AUTO_BOX;
    patchEdit({ box: { ...current, dx: current.dx + dx, dy: current.dy + dy } });
  };

  const setAutoWidth = (auto: boolean) => {
    const { box } = layoutRef.current;
    patchEdit({ box: auto ? { ...geometry, width: null } : { dx: box.x - original[0], dy: geometry.dy, width: box.width } });
  };

  /** Keys while selected (not typing). */
  const onFrameKey = (e: KeyboardEvent) => {
    if (typing) return;
    e.stopPropagation();
    const arrow = NUDGE[e.key];
    if (arrow) {
      e.preventDefault();
      const stepSize = e.shiftKey ? 10 : 1;
      nudge(arrow[0] * stepSize, arrow[1] * stepSize);
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      void remove();
    } else if (e.key === "Enter") {
      e.preventDefault();
      startTyping();
    } else if (e.key === "Escape") {
      void commit();
    }
  };

  const left = layout.box.x * zoom;
  const top = moved[1] * zoom;
  const ghost: CSSProperties | null = pixels
    ? {
        left: moved[0] * zoom,
        top: moved[1] * zoom,
        width: (original[2] - original[0]) * zoom,
        height: (original[3] - original[1]) * zoom,
        backgroundImage: renderSrc ? `url(${renderSrc})` : undefined,
        backgroundSize: `${pageSize[0] * zoom}px ${pageSize[1] * zoom}px`,
        backgroundPosition: `${-original[0] * zoom}px ${-original[1] * zoom}px`,
      }
    : null;

  return (
    <>
      <SnapGuides guides={guides} zoom={zoom} />
      <PushPreview
        selection={push.selection}
        conflicts={push.conflicts}
        dy={push.dy}
        zoom={zoom}
        renderSrc={renderSrc}
        pageSize={pageSize}
        onToggle={push.toggle}
      />
      {ghost && <div className="box-ghost" style={ghost} />}
      <div className="edit-chip" style={{ left, top }} onPointerDown={(e) => e.stopPropagation()}>
        <span className="chip-label">Text box</span>
        {!typing && (
          <button className="icon-btn small" onClick={() => startTyping()} title="Edit the text (double-click or Enter)">
            <Pencil size={14} />
          </button>
        )}
        <button
          className={`icon-btn small${layout.auto ? " active" : ""}`}
          onClick={() => setAutoWidth(!layout.auto)}
          title={layout.auto ? "Auto width: grows as you type, then wraps at the page edge. Click to fix the width." : "Fixed width: text wraps inside the box. Click for auto width."}
          aria-pressed={layout.auto}
        >
          <MoveHorizontal size={14} />
        </button>
        <button className="btn small primary" onClick={() => void commit()} title="Apply (Ctrl+Enter, or click outside)">
          <Check size={14} /> Apply
        </button>
        <button className="icon-btn small" onClick={cancel} title="Discard changes">
          <X size={14} />
        </button>
      </div>
      <TextBoxFrame
        frameRef={frameRef}
        left={left}
        top={top}
        width={layout.box.width * zoom}
        autoWidth={layout.auto}
        selected={!typing}
        onGesture={onGesture}
        onGestureEnd={() => {
          setGuides({});
          // Read the current state: a double-click may have started typing during this gesture.
          if (useEditor.getState().activeEdit?.typing) ref.current?.focus();
          else frameRef.current?.focus({ preventScroll: true });
        }}
        onAutoWidth={() => setAutoWidth(true)}
        onKeyDown={onFrameKey}
      >
        <textarea
          ref={ref}
          className={`block-editor${pixels ? " hidden-text" : ""}`}
          value={text}
          rows={1}
          spellCheck={false}
          wrap="soft"
          readOnly={!typing}
          tabIndex={typing ? 0 : -1}
          style={{
            fontFamily: family,
            fontSize: draft.size * zoom,
            fontWeight: draft.bold ? 700 : 400,
            fontStyle: draft.italic ? "italic" : "normal",
            lineHeight: `${step * zoom}px`,
            color: draft.color,
            opacity: pixels ? 0 : Math.max(draft.opacity, 0.35), // real pixels are shown instead
            textAlign: edit.align,
            textDecoration: [draft.underline && "underline", draft.strike && "line-through"].filter(Boolean).join(" ") || undefined,
          }}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void commit();
            if (e.key === "Escape") patchEdit({ typing: false }); // back to "selected"
            const arrow = NUDGE[e.key];
            if (arrow && e.altKey) {
              e.preventDefault();
              const stepSize = e.shiftKey ? 10 : 1;
              nudge(arrow[0] * stepSize, arrow[1] * stepSize);
            }
          }}
          aria-label="Edit text box"
        />
      </TextBoxFrame>
    </>
  );
}
