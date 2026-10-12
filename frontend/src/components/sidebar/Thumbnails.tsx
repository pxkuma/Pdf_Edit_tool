import { Copy, FilePlus2, RotateCcw, RotateCw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { PageInfo } from "../../api/types";
import { useEditor } from "../../store/editor";

const THUMB_WIDTH = 150;

function Thumb({
  docId,
  page,
  selected,
  current,
  dropSide,
  onClick,
  onDragStart,
  onDragOver,
  onDrop,
}: {
  docId: string;
  page: PageInfo;
  selected: boolean;
  current: boolean;
  dropSide: "before" | "after" | null;
  onClick: (event: React.MouseEvent) => void;
  onDragStart: (event: React.DragEvent) => void;
  onDragOver: (event: React.DragEvent) => void;
  onDrop: (event: React.DragEvent) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => entry.isIntersecting && setInView(true), { rootMargin: "300px" });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const scale = THUMB_WIDTH / page.width;
  const height = page.height * scale;
  const renderScale = Math.min(1, Math.max(0.125, Math.round(scale * Math.min(window.devicePixelRatio || 1, 2) * 8) / 8));

  return (
    <div
      ref={ref}
      className={`thumb${selected ? " selected" : ""}${current ? " current" : ""}${dropSide ? ` drop-${dropSide}` : ""}`}
      draggable
      onClick={onClick}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      title={`Page ${page.index + 1} — drag to reorder`}
    >
      <div className="thumb-img" style={{ width: THUMB_WIDTH, height }}>
        {inView && (
          <img
            src={api.renderUrl(docId, page.index, renderScale, page.token)}
            alt=""
            width={THUMB_WIDTH}
            height={height}
            draggable={false}
            loading="lazy"
            style={{ display: "block", width: THUMB_WIDTH, height }}
          />
        )}
      </div>
      <span className="thumb-num">{page.index + 1}</span>
    </div>
  );
}

export function Thumbnails() {
  const { doc, selectedPages, currentPage, setSelectedPages, scrollTo, run, openDialog } = useEditor();
  const [drag, setDrag] = useState<{ from: number[]; over: number; side: "before" | "after" } | null>(null);
  const anchor = useRef(0);
  if (!doc) return null;
  const pages = doc.pages;
  const targets = selectedPages.length ? selectedPages : [currentPage];

  const onClick = (index: number, event: React.MouseEvent) => {
    if (event.shiftKey) {
      const [a, b] = [Math.min(anchor.current, index), Math.max(anchor.current, index)];
      setSelectedPages(Array.from({ length: b - a + 1 }, (_, i) => a + i));
    } else if (event.ctrlKey || event.metaKey) {
      setSelectedPages(selectedPages.includes(index) ? selectedPages.filter((p) => p !== index) : [...selectedPages, index]);
      anchor.current = index;
    } else {
      setSelectedPages([index]);
      anchor.current = index;
      scrollTo(index);
    }
  };

  const onDrop = async (event: React.DragEvent) => {
    event.preventDefault();
    if (!drag) return;
    const moving = [...drag.from].sort((a, b) => a - b);
    const insertAt = drag.side === "before" ? drag.over : drag.over + 1;
    setDrag(null);
    const remaining = pages.map((p) => p.index).filter((i) => !moving.includes(i));
    const offset = moving.filter((i) => i < insertAt).length;
    const order = [...remaining];
    order.splice(insertAt - offset, 0, ...moving);
    if (order.every((value, i) => value === i)) return;
    await run(() => api.reorderPages(doc.id, order), "Pages reordered");
    setSelectedPages(moving.map((_, i) => insertAt - offset + i));
  };

  return (
    <>
      <div className="row wrap" style={{ gap: 2, marginBottom: 10, justifyContent: "center" }}>
        <button className="icon-btn small" title="Rotate left" onClick={() => run(() => api.rotatePages(doc.id, targets, -90))}>
          <RotateCcw size={15} />
        </button>
        <button className="icon-btn small" title="Rotate right" onClick={() => run(() => api.rotatePages(doc.id, targets, 90))}>
          <RotateCw size={15} />
        </button>
        <button className="icon-btn small" title="Duplicate" onClick={() => run(() => api.duplicatePages(doc.id, targets), "Page duplicated")}>
          <Copy size={15} />
        </button>
        <button className="icon-btn small" title="Insert pages…" onClick={() => openDialog("insertPages")}>
          <FilePlus2 size={15} />
        </button>
        <button
          className="icon-btn small"
          title="Delete"
          disabled={targets.length >= pages.length}
          onClick={() => run(() => api.deletePages(doc.id, targets), `${targets.length} page(s) deleted`)}
        >
          <Trash2 size={15} />
        </button>
      </div>
      <div className="thumbs" onDragLeave={(e) => e.currentTarget === e.target && setDrag(null)}>
        {pages.map((page) => (
          <Thumb
            key={page.index}
            docId={doc.id}
            page={page}
            selected={selectedPages.includes(page.index)}
            current={currentPage === page.index}
            dropSide={drag && drag.over === page.index ? drag.side : null}
            onClick={(e) => onClick(page.index, e)}
            onDragStart={(e) => {
              const from = selectedPages.includes(page.index) ? selectedPages : [page.index];
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData("text/plain", from.join(","));
              setDrag({ from, over: page.index, side: "before" });
            }}
            onDragOver={(e) => {
              e.preventDefault();
              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
              const side = e.clientY < rect.top + rect.height / 2 ? "before" : "after";
              if (drag && (drag.over !== page.index || drag.side !== side)) setDrag({ ...drag, over: page.index, side });
            }}
            onDrop={onDrop}
          />
        ))}
      </div>
      <p className="muted" style={{ textAlign: "center", fontSize: 11, marginTop: 14 }}>
        Ctrl/Shift-click to select several pages · drag to reorder
      </p>
    </>
  );
}
