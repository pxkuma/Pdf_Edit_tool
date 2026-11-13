import { useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api } from "../../api/client";
import type { FormField, PageModel, Rect } from "../../api/types";
import { cssRect, resizeRect, translate, type Handle } from "../../lib/geometry";
import { tooSmall } from "../../lib/formFields";
import { useEditor } from "../../store/editor";
import { startDrag } from "./usePointer";

interface FieldEditLayerProps {
  docId: string;
  model: PageModel | null;
  zoom: number;
}

const HANDLES: Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
const MIN_DRAG = 2; // px: smaller movements are clicks

/**
 * "Edit fields" mode: every form field of the page is a frame to select, move (drag) and resize (handles).
 * What the field is made of is edited in the Properties panel.
 */
export function FieldEditLayer({ docId, model, zoom }: FieldEditLayerProps) {
  const selection = useEditor((s) => s.selection);
  const select = useEditor((s) => s.select);
  const run = useEditor((s) => s.run);
  const toast = useEditor((s) => s.toast);
  const [preview, setPreview] = useState<{ xref: number; rect: Rect } | null>(null);

  useEffect(() => setPreview(null), [model]);

  const commit = async (field: FormField, rect: Rect) => {
    if (tooSmall(rect)) {
      setPreview(null);
      toast("A field must be at least 6 points wide and tall.", "warning");
      return;
    }
    await run(() => api.updateField(docId, field.page, field.xref, { rect }));
  };

  const begin = (event: ReactPointerEvent, field: FormField, handle: Handle | null) => {
    if (field.signed) return; // a signed field is part of the signature and cannot change
    let latest = field.rect;
    startDrag(
      event,
      (dx, dy) => {
        latest = handle ? resizeRect(field.rect, handle, dx / zoom, dy / zoom) : translate(field.rect, dx / zoom, dy / zoom);
        setPreview({ xref: field.xref, rect: latest });
      },
      (dx, dy) => {
        if (Math.abs(dx) < MIN_DRAG && Math.abs(dy) < MIN_DRAG) {
          setPreview(null);
          return;
        }
        void commit(field, latest);
      },
    );
  };

  return (
    <>
      {(model?.fields ?? []).map((field) => {
        const selected = selection?.kind === "field" && selection.page === field.page && selection.xref === field.xref;
        const shown = preview?.xref === field.xref ? preview.rect : field.rect;
        return (
          <div
            key={`${field.page}-${field.xref}`}
            className={`field-box type-${field.type}${selected ? " selected" : ""}`}
            style={cssRect(shown, zoom)}
            title={`${field.name} (${field.type})`}
            onPointerDown={(event) => {
              event.stopPropagation();
              if (!selected) select({ kind: "field", page: field.page, xref: field.xref });
              begin(event, field, null);
            }}
          >
            <span className="field-tab" aria-hidden="true">{field.tabIndex + 1}</span>
            {selected && <span className="field-name">{field.name}</span>}
            {selected &&
              !field.signed &&
              HANDLES.map((handle) => (
                <span key={handle} className={`handle ${handle}`} onPointerDown={(event) => begin(event, field, handle)} />
              ))}
          </div>
        );
      })}
    </>
  );
}
