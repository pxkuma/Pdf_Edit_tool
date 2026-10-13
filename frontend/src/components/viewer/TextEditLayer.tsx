import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { PageModel, Rect, TextBlock } from "../../api/types";
import { api } from "../../api/client";
import { useBackgrounds } from "../../lib/background";
import { flushEdit, registerCommit } from "../../lib/editSession";
import { cssRect, type Handle } from "../../lib/geometry";
import { moveRect, pageObjects, resizeObject, textBoxes, type PageObject, type TextBox } from "../../lib/objects";
import { pushCandidates } from "../../lib/push";
import { SNAP_PX, snapBox, snapTargets, type Guides } from "../../lib/snap";
import { textBoxLines } from "../../lib/textBox";
import { useEditor } from "../../store/editor";
import { BlockEditor } from "./BlockEditor";
import { beginBlockEdit, beginSpanEdit } from "./editHelpers";
import { ObjectFrame } from "./ObjectFrame";
import { SnapGuides } from "./SnapGuides";
import { SpanEditor } from "./SpanEditor";
import { trackPointer } from "./usePointer";

interface TextEditLayerProps {
  docId: string;
  page: number;
  model: PageModel | null;
  zoom: number;
  pageSize: [number, number];
  renderSrc: string | null;
}

const DRAG_THRESHOLD = 3; // px before a press becomes a drag
const DOUBLE_PRESS_MS = 450;
const NUDGE_COMMIT_MS = 600;
const same = (a: Rect, b: Rect, tolerance = 1) => a.every((v, i) => Math.abs(v - b[i]) <= tolerance);
const padRect = (r: Rect, pad: number): Rect => [r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad];

/**
 * Edit mode, Canva-style: every text box, image and vector graphic on the page
 * can be grabbed. Press and drag to move it straight away; a selected object
 * shows handles to resize it. Text boxes are typed into with a double-click.
 */
export function TextEditLayer({ docId, page, model, zoom, pageSize, renderSrc }: TextEditLayerProps) {
  const activeEdit = useEditor((s) => (s.activeEdit?.page === page ? s.activeEdit : null));
  const setActiveEdit = useEditor((s) => s.setActiveEdit);
  const patchEdit = useEditor((s) => s.patchEdit);
  const run = useEditor((s) => s.run);
  const blocks = model?.text.blocks ?? [];
  const boxes = useMemo(() => (model ? textBoxes(model) : []), [model]);
  const objects = useMemo(() => (model ? pageObjects(model) : []), [model]);
  const [selected, setSelected] = useState<PageObject | null>(null);
  const [preview, setPreview] = useState<Rect | null>(null);
  const [guides, setGuides] = useState<Guides>({});
  const nudgeTimer = useRef<number | undefined>(undefined);
  const lastBoxPress = useRef<{ key: string; at: number }>({ key: "", at: 0 });
  const pendingRect = useRef<Rect | null>(null);

  // The text box a span belongs to (for the single-run editor's "edit as text box").
  const blockOf = useMemo(() => {
    const map = new Map<string, TextBlock>();
    for (const block of blocks) for (const line of block.lines) for (const s of line.spans) map.set(s.id, textBoxLines(block, line.id));
    return map;
  }, [blocks]);

  const editingSpans = useMemo(() => new Set(activeEdit?.boxSpanIds ?? (activeEdit ? [activeEdit.span.id] : [])), [activeEdit]);
  const obstacles = useMemo(
    () =>
      blocks.flatMap((block) =>
        block.lines.filter((line) => !line.spans.some((s) => editingSpans.has(s.id))).map((line) => ({ id: line.id, bbox: line.bbox })),
      ),
    [blocks, editingSpans],
  );
  const candidates = useMemo(() => (model ? pushCandidates(model, editingSpans) : []), [model, editingSpans]);
  const coverRect = activeEdit ? (activeEdit.mode === "block" && activeEdit.blockBbox ? activeEdit.blockBbox : activeEdit.span.bbox) : null;
  const [background, objectBackground] = useBackgrounds(renderSrc, pageSize[0], [coverRect ?? [0, 0, 1, 1], selected?.bbox ?? [0, 0, 1, 1]]);

  // After the page changes, keep the moved/resized object selected (found by its new place).
  // An older page model can still arrive while a change is being applied: keep the
  // selection (shown at its new place) until the page with the change is here.
  const inflight = useRef(0);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  useEffect(() => {
    const current = selectedRef.current;
    if (!model || !current) return;
    const place = pendingRect.current ?? current.bbox;
    const found = objects.find((o) => o.kind === current.kind && (o.xref ? o.xref === current.xref : true) && same(o.bbox, place, 1.5));
    if (found) {
      pendingRect.current = null;
      setSelected(found);
      setPreview(null);
    } else if (inflight.current === 0) {
      pendingRect.current = null;
      setSelected(null);
      setPreview(null);
    }
  }, [model, objects]);

  const snapTargetsFor = (exclude: Rect) =>
    snapTargets(
      [...obstacles.map((o) => o.bbox), ...objects.map((o) => o.bbox)].filter((r) => !same(r, exclude, 0.01)),
      { width: pageSize[0], height: pageSize[1] },
    );

  // ------------------------------------------------------------ images / graphics
  const commitObject = async (object: PageObject, to: Rect) => {
    if (same(object.bbox, to, 0.05)) return;
    pendingRect.current = to;
    inflight.current += 1;
    try {
      const result = await run(() =>
        api.transformObjects(docId, { page, items: [{ kind: object.kind, bbox: object.bbox, xref: object.xref }], from_rect: object.bbox, to_rect: to }),
      );
      if (result === undefined) {
        pendingRect.current = null; // failed: show it where it really is
      } else {
        // It is there now: later moves start from the new place even before the page reloads.
        setSelected((cur) => (cur && cur.key === object.key ? { ...cur, bbox: to, hit: to } : cur));
      }
      setPreview(null);
    } finally {
      inflight.current -= 1;
    }
  };

  const dragObject = (object: PageObject, from: Rect, event: { clientX: number; clientY: number }, handle: Handle | null) => {
    const targets = snapTargetsFor(object.bbox);
    let latest = from;
    let dragging = false;
    trackPointer(
      event.clientX,
      event.clientY,
      (dx, dy, e) => {
        if (!dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
        dragging = true;
        if (handle) {
          const keepAspect = object.kind === "image" ? !e.shiftKey : e.shiftKey;
          latest = resizeObject(from, handle, dx / zoom, dy / zoom, keepAspect);
        } else {
          const proposed = moveRect(from, dx / zoom, dy / zoom);
          const box = { x: proposed[0], y: proposed[1], width: proposed[2] - proposed[0], height: proposed[3] - proposed[1] };
          const snapped = e.altKey ? { ...box, guides: {} } : snapBox(box, targets, SNAP_PX / zoom);
          setGuides(snapped.guides);
          latest = moveRect(from, snapped.x - from[0], snapped.y - from[1]);
        }
        setPreview(latest);
      },
      () => {
        setGuides({});
        if (dragging) void commitObject(object, latest);
      },
    );
  };

  const pressObject = (object: PageObject, event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    void flushEdit();
    setSelected(object);
    setPreview(null);
    dragObject(object, object.bbox, event, null);
  };

  const nudgeObject = (dx: number, dy: number) => {
    if (!selected) return;
    const next = moveRect(preview ?? selected.bbox, dx, dy);
    setPreview(next);
    window.clearTimeout(nudgeTimer.current);
    nudgeTimer.current = window.setTimeout(() => void commitObject(selected, next), NUDGE_COMMIT_MS);
  };

  const deleteObject = async () => {
    if (!selected) return;
    const object = selected;
    setSelected(null);
    await run(() => api.deleteObjects(docId, { page, items: [{ kind: object.kind, bbox: object.bbox, xref: object.xref }] }), "Deleted");
  };

  // ------------------------------------------------------------ text boxes
  const pressBox = (box: TextBox, event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    setSelected(null);
    const now = Date.now();
    const double = lastBoxPress.current.key === box.key && now - lastBoxPress.current.at < DOUBLE_PRESS_MS;
    lastBoxPress.current = { key: box.key, at: now };
    const current = useEditor.getState().activeEdit;
    if (double && current?.blockId === box.block.id && current.blockBbox === box.block.bbox) {
      startTypingIn(box, event); // a fast double-click: the second press reached the box itself
      return;
    }
    void flushEdit();
    const edit = beginBlockEdit(page, box.block, undefined, { typing: false, uniform: box.uniform && !box.ocr, pressedAt: now });
    if (!edit) return;
    setActiveEdit(edit);
    // Press-and-drag moves the box straight away.
    const targets = snapTargetsFor(box.bbox);
    const [x0, y0, x1, y1] = box.bbox;
    let dragging = false;
    trackPointer(
      event.clientX,
      event.clientY,
      (dx, dy, e) => {
        if (!dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
        dragging = true;
        const proposed = { x: x0 + dx / zoom, y: y0 + dy / zoom, width: x1 - x0, height: y1 - y0 };
        const snapped = e.altKey ? { ...proposed, guides: {} } : snapBox(proposed, targets, SNAP_PX / zoom);
        setGuides(snapped.guides);
        patchEdit({ box: { dx: snapped.x - x0, dy: snapped.y - y0, width: null } });
      },
      () => setGuides({}),
    );
  };

  /** Double-click on a box: type into it, or edit the run under the pointer if styles are mixed. */
  const startTypingIn = (box: TextBox, event: ReactPointerEvent) => {
    if (box.uniform && !box.ocr) {
      patchEdit({ typing: true });
      return;
    }
    const rect = (event.currentTarget as HTMLElement).parentElement?.getBoundingClientRect();
    const point = rect ? [(event.clientX - rect.left) / zoom, (event.clientY - rect.top) / zoom] : null;
    const spans = box.block.lines.flatMap((l) => l.spans);
    const target =
      (point && spans.find((s) => point[0] >= s.bbox[0] && point[0] <= s.bbox[2] && point[1] >= s.bbox[1] && point[1] <= s.bbox[3])) ??
      spans[0];
    registerCommit(null);
    setActiveEdit(beginSpanEdit(page, target));
  };

  const onBackgroundDown = () => {
    setSelected(null);
    void flushEdit();
  };

  return (
    <div className="layer" onPointerDown={onBackgroundDown}>
      {objects.map((object) =>
        selected?.key === object.key ? null : (
          <div
            key={object.key}
            className="obj-hit"
            style={cssRect(object.hit, zoom)}
            title={object.kind === "image" ? "Image — drag to move, click to resize" : "Graphic — drag to move, click to resize"}
            onPointerDown={(e) => pressObject(object, e)}
          />
        ),
      )}
      {boxes.map((box) =>
        box.block.lines.some((l) => l.spans.some((s) => editingSpans.has(s.id))) ? null : (
          <div
            key={box.key}
            className={`obj-hit text${box.ocr ? " ocr" : ""}`}
            style={cssRect(box.bbox, zoom)}
            title={box.ocr ? "Scanned text (OCR) — drag to move, double-click to edit" : "Text — drag to move, double-click to edit"}
            onPointerDown={(e) => pressBox(box, e)}
          />
        ),
      )}
      {selected && (
        <ObjectFrame
          key={selected.key}
          rect={preview ?? selected.bbox}
          original={selected.bbox}
          zoom={zoom}
          renderSrc={renderSrc}
          pageSize={pageSize}
          background={objectBackground ?? "#fff"}
          label={selected.kind === "image" ? "Image" : "Graphic"}
          onBodyDown={(e) => dragObject(selected, preview ?? selected.bbox, e, null)}
          onHandleDown={(handle, e) => dragObject(selected, preview ?? selected.bbox, e, handle)}
          onNudge={nudgeObject}
          onDelete={() => void deleteObject()}
          onDeselect={() => setSelected(null)}
        />
      )}
      {coverRect && (
        // Slightly larger than the text box so no antialiased glyph edge peeks out.
        <div className="obj-cover" style={{ ...cssRect(padRect(coverRect, 1.2), zoom), background: background ?? "#fff" }} />
      )}
      <SnapGuides guides={guides} zoom={zoom} />
      {activeEdit?.mode === "span" && (
        <SpanEditor
          key={activeEdit.span.id}
          docId={docId}
          edit={activeEdit}
          zoom={zoom}
          block={blockOf.get(activeEdit.span.id) ?? null}
          background={background ?? "#fff"}
        />
      )}
      {activeEdit?.mode === "block" && (
        <BlockEditor
          key={`blk-${activeEdit.span.id}`}
          docId={docId}
          edit={activeEdit}
          zoom={zoom}
          obstacles={obstacles}
          candidates={candidates}
          renderSrc={renderSrc}
          pageSize={pageSize}
        />
      )}
    </div>
  );
}
