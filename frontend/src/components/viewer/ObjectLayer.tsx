import { useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api } from "../../api/client";
import type { Annotation, PageImage, PageModel, Rect } from "../../api/types";
import { cssRect, resizeRect, translate, type Handle } from "../../lib/geometry";
import { useEditor } from "../../store/editor";
import { startDrag } from "./usePointer";

interface ObjectLayerProps {
  docId: string;
  page: number;
  model: PageModel | null;
  zoom: number;
}

const HANDLES: Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

export function annotationStyle(annot: Annotation) {
  return {
    color: annot.color,
    fill: annot.fill,
    opacity: annot.opacity,
    width: annot.width,
    dashed: false,
    contents: annot.contents,
    author: annot.author,
  };
}

export function ObjectLayer({ docId, page, model, zoom }: ObjectLayerProps) {
  const selection = useEditor((s) => s.selection);
  const select = useEditor((s) => s.select);
  const run = useEditor((s) => s.run);
  const [preview, setPreview] = useState<{ key: string; rect: Rect } | null>(null);

  useEffect(() => setPreview(null), [model]);

  const annotations = model?.annotations ?? [];
  const images = (model?.images ?? []).filter((img) => img.editable);

  const commitAnnotation = async (annot: Annotation, rect: Rect) => {
    await run(() => api.updateAnnotation(docId, page, annot.xref, annotationStyle(annot), rect));
  };

  const commitImage = async (image: PageImage, rect: Rect) => {
    await run(() => api.moveImage(docId, page, image.xref, rect));
  };

  const beginDrag = (
    event: ReactPointerEvent,
    key: string,
    rect: Rect,
    handle: Handle | null,
    onCommit: (rect: Rect) => Promise<void>,
  ) => {
    let latest = rect;
    startDrag(
      event,
      (dx, dy) => {
        latest = handle ? resizeRect(rect, handle, dx / zoom, dy / zoom) : translate(rect, dx / zoom, dy / zoom);
        setPreview({ key, rect: latest });
      },
      (dx, dy) => {
        if (Math.abs(dx) < 2 && Math.abs(dy) < 2) {
          setPreview(null);
          return;
        }
        void onCommit(latest);
      },
    );
  };

  const renderBox = (
    key: string,
    rect: Rect,
    selected: boolean,
    onSelect: () => void,
    onCommit: (rect: Rect) => Promise<void>,
    title: string,
    resizable = true,
  ) => {
    const shown = preview?.key === key ? preview.rect : rect;
    return (
      <div
        key={key}
        className={`object-box${selected ? " selected" : ""}`}
        style={cssRect(shown, zoom)}
        title={title}
        onPointerDown={(event) => {
          event.stopPropagation();
          if (!selected) {
            onSelect();
            return;
          }
          beginDrag(event, key, rect, null, onCommit);
        }}
      >
        {selected &&
          resizable &&
          HANDLES.map((handle) => (
            <span
              key={handle}
              className={`handle ${handle}`}
              onPointerDown={(event) => beginDrag(event, key, rect, handle, onCommit)}
            />
          ))}
      </div>
    );
  };

  return (
    <>
      {images.map((image) =>
        renderBox(
          `img-${image.xref}-${image.bbox.join(",")}`,
          image.bbox,
          selection?.kind === "image" && selection.page === page && selection.xref === image.xref,
          () => select({ kind: "image", page, xref: image.xref }),
          (rect) => commitImage(image, rect),
          "Image — click to select, drag to move",
        ),
      )}
      {annotations.map((annot) =>
        renderBox(
          `an-${annot.xref}`,
          annot.rect,
          selection?.kind === "annotation" && selection.page === page && selection.xref === annot.xref,
          () => select({ kind: "annotation", page, xref: annot.xref }),
          (rect) => commitAnnotation(annot, rect),
          `${annot.type}${annot.contents ? `: ${annot.contents}` : ""}`,
          !["Highlight", "Underline", "StrikeOut", "Squiggly", "Text"].includes(annot.type),
        ),
      )}
    </>
  );
}
