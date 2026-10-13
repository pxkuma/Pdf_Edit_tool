import { Download, ImageUp, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Annotation, PageImage } from "../../api/types";
import { pickFile } from "../../lib/files";
import { loadPageModel } from "../../lib/pageModel";
import { useEditor } from "../../store/editor";
import { ColorPicker } from "../common/ColorPicker";
import { NumberField } from "../common/NumberField";
import { annotationStyle } from "../viewer/ObjectLayer";
import { ObjectGeometry } from "./ObjectGeometry";

function useSelectedObject() {
  const doc = useEditor((s) => s.doc);
  const selection = useEditor((s) => s.selection);
  const [object, setObject] = useState<Annotation | PageImage | null>(null);
  const page = selection ? doc?.pages[selection.page] : undefined;
  useEffect(() => {
    if (!doc || !selection || !page) {
      setObject(null);
      return;
    }
    let alive = true;
    loadPageModel(doc.id, page.index, page.token).then((model) => {
      if (!alive) return;
      const found =
        selection.kind === "annotation"
          ? model.annotations.find((a) => a.xref === selection.xref)
          : model.images.find((i) => i.xref === selection.xref);
      setObject(found ?? null);
    });
    return () => {
      alive = false;
    };
  }, [doc, selection, page]);
  return { doc, selection, object };
}

const FILLABLE = ["Square", "Circle", "FreeText", "Line"];
const NO_WIDTH = ["Highlight", "Text"];

export function SelectedObjectProps() {
  const { doc, selection, object } = useSelectedObject();
  const run = useEditor((s) => s.run);
  const select = useEditor((s) => s.select);
  if (doc && selection?.kind === "graphic") {
    return (
      <div className="prop-section">
        <h4>Graphic</h4>
        <ObjectGeometry key={selection.bbox.join(",")} selection={selection} />
        <button
          className="btn small danger"
          onClick={async () => {
            select(null);
            await run(() => api.deleteObjects(doc.id, { page: selection.page, items: [{ kind: "drawing", bbox: selection.bbox }] }), "Deleted");
          }}
        >
          <Trash2 size={14} /> Delete
        </button>
        <p className="muted" style={{ margin: 0, fontSize: 12 }}>
          Drag to move, drag the handles to resize (Shift keeps proportions). Arrow keys nudge, Delete removes.
        </p>
      </div>
    );
  }
  if (!doc || !selection || !object) return null;

  if (selection.kind === "image") {
    const image = object as PageImage;
    return (
      <div className="prop-section">
        <h4>Image</h4>
        <div className="note">
          {image.width} × {image.height} px
          {image.uses > 1 && <div style={{ color: "var(--warning)" }}>Used {image.uses}× in this document — changes apply to every copy.</div>}
        </div>
        <button
          className="btn small"
          onClick={async () => {
            const file = await pickFile("image/*");
            if (file) await run(() => api.replaceImage(doc.id, selection.page, image.xref, file), "Image replaced");
          }}
        >
          <ImageUp size={14} /> Replace image…
        </button>
        {selection.bbox && <ObjectGeometry key={selection.bbox.join(",")} selection={selection} />}
        <a className="btn small" href={api.imageUrl(doc.id, image.xref)} download>
          <Download size={14} /> Save image
        </a>
        <button
          className="btn small danger"
          onClick={async () => {
            select(null);
            const bbox = selection.bbox;
            await run(
              () =>
                bbox
                  ? api.deleteObjects(doc.id, { page: selection.page, items: [{ kind: "image", bbox, xref: image.xref }] })
                  : api.deleteImage(doc.id, selection.page, image.xref),
              "Image deleted",
            );
          }}
        >
          <Trash2 size={14} /> Delete image
        </button>
        <p className="muted" style={{ margin: 0, fontSize: 12 }}>
          Drag to move, drag the handles to resize (corners keep proportions, Shift stretches). Arrow keys nudge, Delete removes.
        </p>
      </div>
    );
  }

  const annot = object as Annotation;
  const update = (patch: Partial<ReturnType<typeof annotationStyle>>) =>
    run(() => api.updateAnnotation(doc.id, selection.page, annot.xref, { ...annotationStyle(annot), ...patch }));

  return (
    <div className="prop-section">
      <h4>{annot.type === "Text" ? "Sticky note" : `${annot.type} annotation`}</h4>
      <label className="field">
        <span>{annot.type === "FreeText" ? "Text color" : "Color"}</span>
        <ColorPicker value={annot.color} onChange={(color) => update({ color })} />
      </label>
      {FILLABLE.includes(annot.type) && (
        <label className="field">
          <span>Fill</span>
          <ColorPicker value={annot.fill} allowNone onChange={(fill) => update({ fill })} />
        </label>
      )}
      <div className="grid-2">
        <label className="field">
          <span>Opacity</span>
          <NumberField value={Math.round(annot.opacity * 100)} min={5} max={100} step={5} suffix="%" onChange={(v) => update({ opacity: v / 100 })} />
        </label>
        {!NO_WIDTH.includes(annot.type) && (
          <label className="field">
            <span>Line width</span>
            <NumberField value={annot.width} min={0} max={30} step={0.5} suffix="pt" onChange={(width) => update({ width })} />
          </label>
        )}
      </div>
      <label className="field">
        <span>Comment</span>
        <textarea
          className="textarea"
          defaultValue={annot.contents}
          key={annot.xref + annot.contents}
          placeholder="Add a comment…"
          onKeyDown={(e) => e.stopPropagation()}
          onBlur={(e) => e.target.value !== annot.contents && update({ contents: e.target.value })}
        />
      </label>
      <button
        className="btn small danger"
        onClick={async () => {
          select(null);
          await run(() => api.deleteAnnotation(doc.id, selection.page, annot.xref), "Annotation deleted");
        }}
      >
        <Trash2 size={14} /> Delete
      </button>
    </div>
  );
}
