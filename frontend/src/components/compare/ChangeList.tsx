import { FilePlus2, FileX2, Image as ImageIcon, Minus, Plus, Replace, Ruler } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import type { CompareChange } from "../../api/compareTypes";
import { changeDetail, changeLabel, pageRef } from "../../lib/compare";

interface ChangeListProps {
  changes: CompareChange[];
  activeId: string | null;
  onSelect: (id: string) => void;
  empty: string;
}

function icon(change: CompareChange): ReactNode {
  if (change.kind === "visual") return <ImageIcon size={14} />;
  if (change.kind === "page") {
    if (change.type === "insert") return <FilePlus2 size={14} />;
    if (change.type === "delete") return <FileX2 size={14} />;
    return <Ruler size={14} />;
  }
  if (change.type === "insert") return <Plus size={14} />;
  if (change.type === "delete") return <Minus size={14} />;
  return <Replace size={14} />;
}

function tone(change: CompareChange): string {
  if (change.kind === "visual") return "visual";
  if (change.kind === "page") return change.type === "insert" ? "insert" : change.type === "delete" ? "delete" : "visual";
  return change.type === "replace" ? "replace" : change.type;
}

/** Every difference, in reading order. Choosing one shows it on both pages. */
export function ChangeList({ changes, activeId, onSelect, empty }: ChangeListProps) {
  const activeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeId]);

  if (!changes.length) return <p className="prop-empty">{empty}</p>;

  return (
    <ul className="cmp-list" aria-label="Differences">
      {changes.map((change) => {
        const active = change.id === activeId;
        return (
          <li key={change.id}>
            <button
              ref={active ? activeRef : undefined}
              className={`cmp-item ${tone(change)}${active ? " active" : ""}`}
              aria-current={active ? "true" : undefined}
              onClick={() => onSelect(change.id)}
            >
              <span className="cmp-item-icon">{icon(change)}</span>
              <span className="cmp-item-body">
                <span className="cmp-item-head">
                  <strong>{changeLabel(change)}</strong>
                  <span>{pageRef(change)}</span>
                </span>
                <span className="cmp-item-detail">{changeDetail(change)}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
