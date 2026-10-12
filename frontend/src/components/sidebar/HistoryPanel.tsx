import { History, RotateCcw } from "lucide-react";
import { api } from "../../api/client";
import { flushEdit } from "../../lib/editSession";
import { useEditor } from "../../store/editor";

function time(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function HistoryPanel() {
  const { doc, setDoc, track, run } = useEditor();
  if (!doc) return null;

  const jump = async (index: number) => {
    await flushEdit();
    const info = await track(() => api.jump(doc.id, index));
    if (info) setDoc(info);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="list">
        {doc.history.map((entry, index) => (
          <button
            key={index}
            className={`list-item${index === doc.cursor ? " on" : ""}`}
            style={{ opacity: index > doc.cursor ? 0.5 : 1 }}
            onClick={() => jump(index)}
            title={index > doc.cursor ? "Redo up to here" : "Go back to this state"}
          >
            <History size={13} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{entry.label}</span>
            <small>{time(entry.ts)}</small>
          </button>
        ))}
      </div>
      <button className="btn small danger" onClick={() => run(() => api.revert(doc.id), "Reverted to the original file")}>
        <RotateCcw size={14} /> Revert to original
      </button>
      <p className="muted" style={{ fontSize: 11 }}>
        Every change is kept as a version, so you can always step back. Reverting is also undoable.
      </p>
    </div>
  );
}
