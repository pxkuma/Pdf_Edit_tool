import { Copy, Eraser, Highlighter, Strikethrough, Underline } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import { api } from "../../api/client";
import type { PageModel, Point, Rect, Word } from "../../api/types";
import { contains, cssRect, mergeLineRects } from "../../lib/geometry";
import { useEditor } from "../../store/editor";
import { usePagePoint } from "./usePointer";

type MarkupKind = "highlight" | "underline" | "strikeout" | "squiggly";

interface WordSelectLayerProps {
  docId: string;
  page: number;
  model: PageModel | null;
  zoom: number;
  markup: MarkupKind | null; // null = plain selection (select tool)
  pageRef: RefObject<HTMLDivElement>;
}

function nearestWord(words: Word[], point: Point): number {
  let best = -1;
  let bestDistance = Infinity;
  words.forEach((word, index) => {
    if (contains(word.bbox, point, 1)) {
      best = index;
      bestDistance = 0;
      return;
    }
    const dx = Math.max(word.bbox[0] - point[0], 0, point[0] - word.bbox[2]);
    const dy = Math.max(word.bbox[1] - point[1], 0, point[1] - word.bbox[3]);
    const distance = Math.hypot(dx, dy * 2);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  });
  return bestDistance < 14 ? best : -1;
}

export function WordSelectLayer({ docId, page, model, zoom, markup, pageRef }: WordSelectLayerProps) {
  const words = useMemo(() => model?.text.words ?? [], [model]);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [dragging, setDragging] = useState(false);
  const anchor = useRef(-1);
  const toPoint = usePagePoint(pageRef, zoom);
  const run = useEditor((s) => s.run);
  const markupStyle = useEditor((s) => s.markup);
  const toast = useEditor((s) => s.toast);

  useEffect(() => setRange(null), [model]);

  const selected = useMemo(() => {
    if (!range) return [];
    const [a, b] = range[0] <= range[1] ? range : [range[1], range[0]];
    return words.slice(a, b + 1);
  }, [range, words]);
  const lineRects = useMemo(() => mergeLineRects(selected.map((w) => w.bbox)), [selected]);

  const apply = async (kind: MarkupKind, rects: Rect[]) => {
    setRange(null);
    await run(() =>
      api.addAnnotation(docId, {
        page,
        kind,
        rects,
        style: { color: markupStyle.color, opacity: markupStyle.opacity, width: 1, fill: null, dashed: false, contents: "", author: "" },
      }),
    );
  };

  const onPointerDown = (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    const index = nearestWord(words, toPoint(event));
    if (index < 0) {
      setRange(null);
      return;
    }
    event.preventDefault();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    anchor.current = index;
    setRange([index, index]);
    setDragging(true);
  };

  const onPointerMove = (event: ReactPointerEvent) => {
    if (!dragging || anchor.current < 0) return;
    const index = nearestWord(words, toPoint(event));
    if (index >= 0) setRange([anchor.current, index]);
  };

  const onPointerUp = () => {
    if (!dragging) return;
    setDragging(false);
    if (markup && lineRects.length) void apply(markup, lineRects);
  };

  const copy = async () => {
    const text = selected.map((w, i) => (i && selected[i - 1].line !== w.line ? "\n" : i ? " " : "") + w.text).join("");
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied to clipboard", "success");
    } catch {
      toast("Clipboard is not available in this browser context.", "warning");
    }
  };

  const redact = async () => {
    const rects = lineRects;
    setRange(null);
    await run(() => api.redact(docId, page, rects, "redact", "#000000"), "Text redacted");
  };

  const barAnchor = lineRects[0];
  const showBar = !markup && !dragging && lineRects.length > 0 && barAnchor;

  return (
    <div
      className="layer text-cursor"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      style={{ cursor: words.length ? "text" : "default" }}
    >
      {lineRects.map((rect, i) => (
        <div key={i} className="word-sel" style={cssRect(rect, zoom)} />
      ))}
      {showBar && (
        <div
          className="selection-bar"
          style={{ left: ((barAnchor[0] + barAnchor[2]) / 2) * zoom, top: barAnchor[1] * zoom }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <button className="icon-btn small" title="Copy" onClick={copy}>
            <Copy size={15} />
          </button>
          <button className="icon-btn small" title="Highlight" onClick={() => apply("highlight", lineRects)}>
            <Highlighter size={15} />
          </button>
          <button className="icon-btn small" title="Underline" onClick={() => apply("underline", lineRects)}>
            <Underline size={15} />
          </button>
          <button className="icon-btn small" title="Strikethrough" onClick={() => apply("strikeout", lineRects)}>
            <Strikethrough size={15} />
          </button>
          <button className="icon-btn small" title="Redact (permanently remove)" onClick={redact}>
            <Eraser size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
