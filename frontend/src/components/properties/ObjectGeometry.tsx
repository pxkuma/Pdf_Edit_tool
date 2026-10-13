import { Lock, Unlock } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import type { Rect } from "../../api/types";
import { useEditor } from "../../store/editor";
import { NumberField } from "../common/NumberField";

type GeometrySelection =
  | { kind: "image"; page: number; xref: number; bbox?: Rect }
  | { kind: "graphic"; page: number; xref: number; bbox: Rect };

const round = (v: number) => Math.round(v * 100) / 100;

/** Exact position and size of the selected image or graphic (points). */
export function ObjectGeometry({ selection }: { selection: GeometrySelection }) {
  const doc = useEditor((s) => s.doc);
  const run = useEditor((s) => s.run);
  const select = useEditor((s) => s.select);
  const [locked, setLocked] = useState(selection.kind === "image");
  if (!doc || !selection.bbox) return null;
  const bbox = selection.bbox;
  const [x0, y0, x1, y1] = bbox;
  const w = x1 - x0;
  const h = y1 - y0;

  const apply = async (to: Rect) => {
    if (to.every((v, i) => Math.abs(v - bbox[i]) < 0.01)) return;
    const kind = selection.kind === "image" ? "image" : "drawing";
    const result = await run(() =>
      api.transformObjects(doc.id, { page: selection.page, items: [{ kind, bbox, xref: selection.xref }], from_rect: bbox, to_rect: to }),
    );
    if (result !== undefined) select({ ...selection, bbox: to } as GeometrySelection);
  };

  const setSize = (width: number | null, height: number | null) => {
    let nw = width ?? w;
    let nh = height ?? h;
    if (locked && w > 0 && h > 0) {
      if (width !== null) nh = (nw / w) * h;
      else nw = (nh / h) * w;
    }
    void apply([x0, y0, x0 + nw, y0 + nh]);
  };

  return (
    <div className="field">
      <span className="field-label">Position and size</span>
      <div className="grid-2">
        <label className="field">
          <span>X</span>
          <NumberField value={round(x0)} step={1} suffix="pt" label="Left" onChange={(x) => void apply([x, y0, x + w, y1])} />
        </label>
        <label className="field">
          <span>Y</span>
          <NumberField value={round(y0)} step={1} suffix="pt" label="Top" onChange={(y) => void apply([x0, y, x1, y + h])} />
        </label>
        <label className="field">
          <span>W</span>
          <NumberField value={round(w)} min={1} step={1} suffix="pt" label="Width" onChange={(v) => setSize(v, null)} />
        </label>
        <label className="field">
          <span>H</span>
          <NumberField value={round(h)} min={0.5} step={1} suffix="pt" label="Height" onChange={(v) => setSize(null, v)} />
        </label>
      </div>
      <label className="check">
        <button className="icon-btn small" onClick={() => setLocked(!locked)} aria-pressed={locked} title="Keep proportions">
          {locked ? <Lock size={14} /> : <Unlock size={14} />}
        </button>
        Keep proportions
      </label>
    </div>
  );
}
