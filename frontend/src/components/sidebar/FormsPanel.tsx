import { CheckSquare, TextCursorInput, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { FormField } from "../../api/types";
import { useEditor } from "../../store/editor";

export function FormsPanel() {
  const { doc, run, scrollTo, setTool } = useEditor();
  const [fields, setFields] = useState<FormField[] | null>(null);

  useEffect(() => {
    if (!doc) return;
    let alive = true;
    api.forms(doc.id).then((f) => alive && setFields(f)).catch(() => alive && setFields([]));
    return () => {
      alive = false;
    };
  }, [doc?.id, doc?.version]);

  if (!doc || fields === null) return <div className="empty">Loading…</div>;

  const update = (field: FormField, value: string | boolean) =>
    run(() => api.fillForms(doc.id, [{ page: field.page, xref: field.xref, value }]));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="grid-2">
        <button className="btn small" onClick={() => setTool("fieldText")}>
          <TextCursorInput size={14} /> Text field
        </button>
        <button className="btn small" onClick={() => setTool("fieldCheckbox")}>
          <CheckSquare size={14} /> Checkbox
        </button>
      </div>
      {fields.length === 0 && <div className="empty">This document has no form fields. Add some with the buttons above.</div>}
      {fields.map((field) => (
        <div key={`${field.page}-${field.xref}`} className="field">
          <div className="row between">
            <button className="btn ghost small" style={{ padding: 0 }} onClick={() => scrollTo(field.page, field.rect[1])}>
              <span className="field-label">
                {field.label || field.name}
                {field.required && " *"}
              </span>
            </button>
            <div className="row" style={{ gap: 2 }}>
              <span className="muted" style={{ fontSize: 11 }}>p.{field.page + 1}</span>
              <button className="icon-btn small" title="Delete field" onClick={() => run(() => api.deleteField(doc.id, field.page, field.xref))}>
                <Trash2 size={13} />
              </button>
            </div>
          </div>
          {field.type === "checkbox" || field.type === "radio" ? (
            <label className="check">
              <input type="checkbox" checked={Boolean(field.value)} disabled={field.readOnly} onChange={(e) => update(field, e.target.checked)} />
              {field.onState && field.onState !== "Yes" ? field.onState : "Checked"}
            </label>
          ) : field.type === "combobox" || field.type === "listbox" ? (
            <select className="select small" value={String(field.value)} disabled={field.readOnly} onChange={(e) => update(field, e.target.value)}>
              <option value="" />
              {field.options.map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          ) : field.type === "text" ? (
            <input
              className="input small"
              defaultValue={String(field.value)}
              disabled={field.readOnly}
              maxLength={field.maxLength || undefined}
              onBlur={(e) => e.target.value !== field.value && update(field, e.target.value)}
              onKeyDown={(e) => e.stopPropagation()}
            />
          ) : (
            <span className="muted">{field.type} field</span>
          )}
        </div>
      ))}
      {fields.length > 0 && (
        <button className="btn small" onClick={() => run(() => api.flatten(doc.id, false, true), "Form flattened")}>
          Flatten form (make values permanent)
        </button>
      )}
    </div>
  );
}
