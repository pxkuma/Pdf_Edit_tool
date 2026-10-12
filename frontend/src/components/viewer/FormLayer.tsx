import { Check } from "lucide-react";
import { useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api } from "../../api/client";
import type { FormField, PageModel } from "../../api/types";
import { cssRect } from "../../lib/geometry";
import { useEditor } from "../../store/editor";

interface FormLayerProps {
  docId: string;
  model: PageModel | null;
  zoom: number;
}

export function FormLayer({ docId, model, zoom }: FormLayerProps) {
  const fields = (model?.fields ?? []).filter((f) => !f.readOnly && ["text", "checkbox", "radio", "combobox", "listbox"].includes(f.type));
  return (
    <>
      {fields.map((field) => (
        <FieldInput key={`${field.xref}-${String(field.value)}`} docId={docId} field={field} zoom={zoom} />
      ))}
    </>
  );
}

function FieldInput({ docId, field, zoom }: { docId: string; field: FormField; zoom: number }) {
  const run = useEditor((s) => s.run);
  const [value, setValue] = useState(field.value);
  useEffect(() => setValue(field.value), [field.value]);

  const save = (next: string | boolean) => {
    if (next === field.value) return;
    void run(() => api.fillForms(docId, [{ page: field.page, xref: field.xref, value: next }]));
  };

  const height = (field.rect[3] - field.rect[1]) * zoom;
  const style = { ...cssRect(field.rect, zoom), fontSize: Math.max(8, Math.min(height * 0.62, 14 * zoom)) };
  const stop = (e: ReactPointerEvent) => e.stopPropagation();

  if (field.type === "checkbox" || field.type === "radio") {
    const checked = Boolean(value);
    return (
      <button
        className="form-field checkbox"
        style={style}
        title={field.name}
        onPointerDown={stop}
        onClick={() => {
          setValue(!checked);
          save(!checked);
        }}
        aria-pressed={checked}
        aria-label={field.label || field.name}
      >
        {checked && <Check size={Math.max(8, height * 0.8)} strokeWidth={3} />}
      </button>
    );
  }
  if (field.type === "combobox" || field.type === "listbox") {
    return (
      <select
        className="form-field"
        style={style}
        value={String(value)}
        title={field.name}
        onPointerDown={stop}
        onChange={(e) => {
          setValue(e.target.value);
          save(e.target.value);
        }}
        aria-label={field.label || field.name}
      >
        <option value="" />
        {field.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }
  const common = {
    className: "form-field",
    style,
    value: String(value),
    title: field.name,
    maxLength: field.maxLength || undefined,
    onPointerDown: stop,
    onBlur: () => save(String(value)),
    "aria-label": field.label || field.name,
  };
  return field.multiline ? (
    <textarea {...common} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
  ) : (
    <input
      {...common}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
    />
  );
}
