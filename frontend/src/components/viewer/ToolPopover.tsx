import { useState } from "react";
import { api } from "../../api/client";
import type { Point, Rect } from "../../api/types";
import { cssRect } from "../../lib/geometry";
import { useEditor } from "../../store/editor";

export type PopoverState =
  | { kind: "note"; point: Point }
  | { kind: "textbox"; rect: Rect }
  | { kind: "crop"; rect: Rect }
  | { kind: "fieldText"; rect: Rect }
  | { kind: "fieldCheckbox"; rect: Rect };

interface ToolPopoverProps {
  docId: string;
  page: number;
  zoom: number;
  state: PopoverState;
  onClose: () => void;
}

export function ToolPopover({ docId, page, zoom, state, onClose }: ToolPopoverProps) {
  const [text, setText] = useState("");
  const { run, shape, newText, doc } = useEditor();
  const anchor: Point = state.kind === "note" ? state.point : [state.rect[0], state.rect[3]];
  const style = { left: anchor[0] * zoom, top: anchor[1] * zoom + 8 };

  const submit = async (action: () => Promise<unknown>) => {
    onClose();
    await action();
  };

  const body = () => {
    switch (state.kind) {
      case "note":
        return (
          <>
            <strong>Sticky note</strong>
            <textarea className="textarea" autoFocus placeholder="Write a comment…" value={text} onChange={(e) => setText(e.target.value)} />
            <Actions
              onCancel={onClose}
              onOk={() =>
                submit(() =>
                  run(() =>
                    api.addAnnotation(docId, {
                      page,
                      kind: "note",
                      point: state.point,
                      text,
                      style: { color: "#ffd400", fill: null, opacity: 1, width: 1, dashed: false, contents: text, author: "" },
                    }),
                  ),
                )
              }
            />
          </>
        );
      case "textbox":
        return (
          <>
            <strong>Text box comment</strong>
            <textarea className="textarea" autoFocus placeholder="Comment text…" value={text} onChange={(e) => setText(e.target.value)} />
            <Actions
              disabled={!text.trim()}
              onCancel={onClose}
              onOk={() =>
                submit(() =>
                  run(() =>
                    api.addAnnotation(docId, {
                      page,
                      kind: "textbox",
                      rect: state.rect,
                      text,
                      font_size: newText.size,
                      text_color: newText.color,
                      style: { color: shape.color, fill: shape.fill ?? "#fffbe6", opacity: 1, width: 1, dashed: false, contents: "", author: "" },
                    }),
                  ),
                )
              }
            />
          </>
        );
      case "crop":
        return (
          <>
            <strong>Crop page</strong>
            <span className="muted">Content outside the box is hidden (not deleted). You can reset the crop later.</span>
            <div className="row wrap">
              <button className="btn small" onClick={onClose}>Cancel</button>
              <button className="btn small" onClick={() => submit(() => run(() => api.cropPages(docId, [page], state.rect), "Page cropped"))}>
                This page
              </button>
              <button
                className="btn small primary"
                onClick={() =>
                  submit(() => run(() => api.cropPages(docId, (doc?.pages ?? []).map((p) => p.index), state.rect), "All pages cropped"))
                }
              >
                All pages
              </button>
            </div>
          </>
        );
      case "fieldText":
      case "fieldCheckbox":
        return (
          <>
            <strong>{state.kind === "fieldText" ? "New text field" : "New checkbox"}</strong>
            <input className="input small" autoFocus placeholder="Field name (optional)" value={text} onChange={(e) => setText(e.target.value)} />
            <Actions
              onCancel={onClose}
              onOk={() =>
                submit(() =>
                  run(
                    () => api.addField(docId, { page, kind: state.kind === "fieldText" ? "text" : "checkbox", rect: state.rect, name: text }),
                    "Form field added",
                  ),
                )
              }
            />
          </>
        );
    }
  };

  return (
    <>
      {state.kind !== "note" && <div className="drag-rect" style={cssRect(state.rect, zoom)} />}
      <div
        className="popover"
        style={style}
        onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Escape") onClose();
        }}
      >
        {body()}
      </div>
    </>
  );
}

function Actions({ onOk, onCancel, disabled }: { onOk: () => void; onCancel: () => void; disabled?: boolean }) {
  return (
    <div className="row" style={{ justifyContent: "flex-end" }}>
      <button className="btn small" onClick={onCancel}>Cancel</button>
      <button className="btn small primary" disabled={disabled} onClick={onOk}>Add</button>
    </div>
  );
}
