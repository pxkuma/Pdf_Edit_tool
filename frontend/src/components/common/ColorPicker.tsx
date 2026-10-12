const PALETTE = ["#000000", "#ffffff", "#e11d48", "#f97316", "#ffd400", "#16a34a", "#0891b2", "#2563eb", "#7c3aed", "#6b7280"];

interface ColorPickerProps {
  value: string | null;
  onChange: (value: string | null) => void;
  allowNone?: boolean;
  palette?: string[];
}

export function ColorPicker({ value, onChange, allowNone, palette = PALETTE }: ColorPickerProps) {
  const current = value?.toLowerCase() ?? null;
  return (
    <div className="swatches">
      {allowNone && (
        <button
          className={`swatch none${current === null ? " on" : ""}`}
          title="No color"
          aria-label="No color"
          onClick={() => onChange(null)}
        />
      )}
      {palette.map((color) => (
        <button
          key={color}
          className={`swatch${current === color ? " on" : ""}`}
          style={{ background: color }}
          title={color}
          aria-label={`Color ${color}`}
          onClick={() => onChange(color)}
        />
      ))}
      <input
        type="color"
        className="color-input"
        value={current ?? "#000000"}
        onChange={(e) => onChange(e.target.value)}
        title="Custom color"
        aria-label="Custom color"
      />
    </div>
  );
}
