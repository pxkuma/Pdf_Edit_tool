import { useMemo, useRef } from "react";
import type { PageModel, Span, TextBlock } from "../../api/types";
import { flushEdit } from "../../lib/editSession";
import { cssRect } from "../../lib/geometry";
import { textBoxLines } from "../../lib/textBox";
import { useEditor } from "../../store/editor";
import { BlockEditor } from "./BlockEditor";
import { beginBlockEdit, beginSpanEdit } from "./editHelpers";
import { SpanEditor } from "./SpanEditor";

interface TextEditLayerProps {
  docId: string;
  page: number;
  model: PageModel | null;
  zoom: number;
  pageWidth: number;
}

export function TextEditLayer({ docId, page, model, zoom, pageWidth }: TextEditLayerProps) {
  const activeEdit = useEditor((s) => (s.activeEdit?.page === page ? s.activeEdit : null));
  const setActiveEdit = useEditor((s) => s.setActiveEdit);
  const blocks = model?.text.blocks ?? [];

  // The text box a span belongs to: its paragraph lines, never other columns of a row.
  const blockOf = useMemo(() => {
    const map = new Map<string, TextBlock>();
    for (const block of blocks) {
      for (const line of block.lines) {
        const box = textBoxLines(block, line.id);
        for (const span of line.spans) map.set(span.id, box);
      }
    }
    return map;
  }, [blocks]);

  const editingSpans = useMemo(() => new Set(activeEdit?.boxSpanIds ?? []), [activeEdit?.boxSpanIds]);
  const obstacles = useMemo(
    () =>
      blocks.flatMap((block) =>
        block.lines.filter((line) => !line.spans.some((s) => editingSpans.has(s.id))).map((line) => ({ id: line.id, bbox: line.bbox })),
      ),
    [blocks, editingSpans],
  );

  const startSpan = async (span: Span) => {
    await flushEdit();
    setActiveEdit(beginSpanEdit(page, span));
  };

  const startBlock = async (span: Span) => {
    const block = blockOf.get(span.id);
    if (!block) return;
    await flushEdit();
    setActiveEdit(beginBlockEdit(page, block));
  };

  const clickTimer = useRef<number | undefined>(undefined);
  const onRunClick = (span: Span, detail: number) => {
    window.clearTimeout(clickTimer.current);
    if (detail >= 2) {
      void startBlock(span);
      return;
    }
    // Wait briefly so a double-click can open paragraph mode instead.
    clickTimer.current = window.setTimeout(() => void startSpan(span), 220);
  };

  const editingId = activeEdit?.span.id;
  const editingBlock = activeEdit?.mode === "block" ? activeEdit.blockBbox : null;

  return (
    <div className="layer text-cursor" onPointerDown={() => void flushEdit()}>
      {blocks.map((block) => (
        <div key={`b${block.id}`} className="block-outline" style={cssRect(block.bbox, zoom)} />
      ))}
      {blocks.flatMap((block) =>
        block.lines.flatMap((line) =>
          line.spans.map((span) => {
            const hidden = span.id === editingId || editingSpans.has(span.id);
            if (hidden) return null;
            return (
              <div
                key={span.id}
                className={span.ocr ? "run ocr" : "run"}
                style={cssRect(span.bbox, zoom)}
                title={span.ocr ? "Scanned text (OCR) — click to edit" : `${span.font} · ${span.size} pt — click to edit, double-click for a text box`}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => onRunClick(span, e.detail)}
              />
            );
          }),
        ),
      )}
      {activeEdit && (
        <div
          style={{ ...cssRect(activeEdit.mode === "block" && editingBlock ? editingBlock : activeEdit.span.bbox, zoom), position: "absolute", background: "#fff" }}
        />
      )}
      {activeEdit?.mode === "span" && (
        <SpanEditor key={activeEdit.span.id} docId={docId} edit={activeEdit} zoom={zoom} block={blockOf.get(activeEdit.span.id) ?? null} />
      )}
      {activeEdit?.mode === "block" && (
        <BlockEditor key={`blk-${activeEdit.span.id}`} docId={docId} edit={activeEdit} zoom={zoom} obstacles={obstacles} pageWidth={pageWidth} />
      )}
    </div>
  );
}
