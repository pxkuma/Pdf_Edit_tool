import { CheckCircle2, CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { DocFont } from "../../api/types";
import { useEditor } from "../../store/editor";

export function FontsPanel() {
  const doc = useEditor((s) => s.doc);
  const [fonts, setFonts] = useState<DocFont[] | null>(null);

  useEffect(() => {
    if (!doc) return;
    let alive = true;
    api.docFonts(doc.id).then((f) => alive && setFonts(f)).catch(() => alive && setFonts([]));
    return () => {
      alive = false;
    };
  }, [doc?.id, doc?.version]);

  if (!fonts) return <div className="empty">Loading…</div>;
  if (!fonts.length) return <div className="empty">No reusable fonts found (the document may be scanned images).</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        Edited text re-uses these fonts directly, so it matches the original exactly. Characters missing from a subset are drawn with the closest installed font.
      </p>
      {fonts.map((font) => (
        <div key={font.xref} className="note" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div className="row between">
            <strong style={{ color: "var(--text)" }}>{font.name}</strong>
            {font.subset ? (
              <span className="badge warn">
                <CircleAlert size={11} /> subset
              </span>
            ) : (
              <span className="badge ok">
                <CheckCircle2 size={11} /> full
              </span>
            )}
          </div>
          <span>
            {font.type} · {font.embedded ? "embedded" : "not embedded"} · {font.glyphs} characters
          </span>
          {font.subset && (
            <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 11, wordBreak: "break-all" }} title="Characters available in this subset">
              {font.chars.trim() || "—"}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
