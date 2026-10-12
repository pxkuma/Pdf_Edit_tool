import { BookmarkPlus, ChevronLeft, ChevronRight, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { TocItem } from "../../api/types";
import { useEditor } from "../../store/editor";

export function OutlinePanel() {
  const { doc, currentPage, scrollTo, run, track } = useEditor();
  const [items, setItems] = useState<TocItem[] | null>(null);
  const [editing, setEditing] = useState<number | null>(null);

  useEffect(() => {
    if (!doc) return;
    let alive = true;
    api.toc(doc.id).then((toc) => alive && setItems(toc)).catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [doc?.id, doc?.version]);

  if (!doc || items === null) return <div className="empty">Loading…</div>;

  const save = async (next: TocItem[]) => {
    setItems(next);
    await run(() => api.setToc(doc.id, next));
  };

  const add = () => {
    void save([...items, { level: 1, title: `Page ${currentPage + 1}`, page: currentPage }]);
    setEditing(items.length);
  };

  const indent = (index: number, delta: number) => {
    const next = items.map((item, i) => (i === index ? { ...item, level: Math.max(1, item.level + delta) } : item));
    void save(next);
  };

  return (
    <div>
      <button className="btn small block" onClick={add}>
        <BookmarkPlus size={14} /> Bookmark current page
      </button>
      {items.length === 0 && <div className="empty">No bookmarks yet.</div>}
      <div className="list" style={{ marginTop: 10 }}>
        {items.map((item, index) => (
          <div key={index} className="row" style={{ paddingLeft: (item.level - 1) * 14, gap: 2 }}>
            {editing === index ? (
              <input
                className="input small"
                autoFocus
                defaultValue={item.title}
                onBlur={(e) => {
                  setEditing(null);
                  if (e.target.value !== item.title) void save(items.map((it, i) => (i === index ? { ...it, title: e.target.value } : it)));
                }}
                onKeyDown={(e) => {
                  e.stopPropagation();
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                }}
              />
            ) : (
              <button className="list-item" onClick={() => scrollTo(item.page)} onDoubleClick={() => setEditing(index)} title="Double-click to rename">
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.title}</span>
                <small>{item.page + 1}</small>
              </button>
            )}
            <button className="icon-btn small" title="Outdent" onClick={() => indent(index, -1)} disabled={item.level <= 1}>
              <ChevronLeft size={13} />
            </button>
            <button className="icon-btn small" title="Indent" onClick={() => indent(index, 1)}>
              <ChevronRight size={13} />
            </button>
            <button className="icon-btn small" title="Remove" onClick={() => void track(() => save(items.filter((_, i) => i !== index)))}>
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
