import { useEffect, useState } from "react";

interface NumberFieldProps {
  value: number | null;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  placeholder?: string;
  label?: string;
}

/** Numeric input that only commits valid, clamped values (on blur / Enter). */
export function NumberField({ value, onChange, min = -Infinity, max = Infinity, step = 1, suffix, placeholder, label }: NumberFieldProps) {
  const [text, setText] = useState(value === null ? "" : String(round(value)));
  useEffect(() => setText(value === null ? "" : String(round(value))), [value]);

  const commit = () => {
    const parsed = Number.parseFloat(text.replace(",", "."));
    if (Number.isNaN(parsed)) {
      setText(value === null ? "" : String(round(value)));
      return;
    }
    const clamped = Math.min(max, Math.max(min, parsed));
    setText(String(round(clamped)));
    if (clamped !== value) onChange(clamped);
  };

  return (
    <div className="row" style={{ gap: 4 }}>
      <input
        className="input small"
        inputMode="decimal"
        value={text}
        placeholder={placeholder}
        aria-label={label}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "ArrowUp" || e.key === "ArrowDown") {
            e.preventDefault();
            const base = value ?? 0;
            const next = Math.min(max, Math.max(min, base + (e.key === "ArrowUp" ? step : -step)));
            onChange(round(next));
          }
        }}
      />
      {suffix && <span className="muted" style={{ fontSize: 11 }}>{suffix}</span>}
    </div>
  );
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
