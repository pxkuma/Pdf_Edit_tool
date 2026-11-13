import { FlipHorizontal2, FlipVertical2, Palette } from "lucide-react";
import { useState } from "react";
import type { ImageAdjust } from "../../api/types";
import { NumberField } from "../common/NumberField";

interface ImageAdjustControlsProps {
  onApply: (body: ImageAdjust, label: string) => Promise<unknown>;
}

const NEUTRAL = { brightness: 100, contrast: 100, saturation: 100 };

/**
 * Canva-style image adjustments. Flips and grayscale apply at once; the sliders
 * collect values and bake them into the image with Apply (the change is destructive
 * for this page's copy, undo restores it).
 */
export function ImageAdjustControls({ onApply }: ImageAdjustControlsProps) {
  const [values, setValues] = useState(NEUTRAL);
  const dirty = values.brightness !== 100 || values.contrast !== 100 || values.saturation !== 100;

  const apply = async () => {
    await onApply(
      { brightness: values.brightness / 100, contrast: values.contrast / 100, saturation: values.saturation / 100 },
      "Image adjusted",
    );
    setValues(NEUTRAL);
  };

  const field = (label: string, key: keyof typeof NEUTRAL) => (
    <label className="field">
      <span>{label}</span>
      <NumberField
        value={values[key]}
        min={10}
        max={300}
        step={5}
        suffix="%"
        onChange={(v) => setValues((current) => ({ ...current, [key]: v }))}
      />
    </label>
  );

  return (
    <>
      <div className="grid-2">
        {field("Brightness", "brightness")}
        {field("Contrast", "contrast")}
      </div>
      <div className="grid-2">
        {field("Saturation", "saturation")}
        <button className="btn small" disabled={!dirty} onClick={() => void apply()} style={{ alignSelf: "end" }}>
          Apply adjustments
        </button>
      </div>
      <div className="grid-2">
        <button className="btn small" onClick={() => void onApply({ flip_h: true }, "Flipped")}>
          <FlipHorizontal2 size={14} /> Flip
        </button>
        <button className="btn small" onClick={() => void onApply({ flip_v: true }, "Flipped")}>
          <FlipVertical2 size={14} /> Flip vertical
        </button>
      </div>
      <button className="btn small" onClick={() => void onApply({ grayscale: true }, "Converted to grayscale")}>
        <Palette size={14} /> Grayscale
      </button>
    </>
  );
}
