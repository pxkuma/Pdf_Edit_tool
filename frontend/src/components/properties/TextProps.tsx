import { AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, Italic, Strikethrough, Underline } from "lucide-react";
import { ColorPicker } from "../common/ColorPicker";
import { FontPicker } from "../common/FontPicker";
import { NumberField } from "../common/NumberField";
import { useEditor } from "../../store/editor";

type Align = "left" | "center" | "right" | "justify";

export function StyleToggles({
  bold,
  italic,
  underline,
  strike,
  onChange,
}: {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strike: boolean;
  onChange: (patch: Partial<{ bold: boolean; italic: boolean; underline: boolean; strike: boolean }>) => void;
}) {
  return (
    <div className="segmented" role="group" aria-label="Text style">
      <button className={bold ? "on" : ""} onClick={() => onChange({ bold: !bold })} title="Bold" aria-pressed={bold}>
        <Bold size={14} />
      </button>
      <button className={italic ? "on" : ""} onClick={() => onChange({ italic: !italic })} title="Italic" aria-pressed={italic}>
        <Italic size={14} />
      </button>
      <button className={underline ? "on" : ""} onClick={() => onChange({ underline: !underline })} title="Underline" aria-pressed={underline}>
        <Underline size={14} />
      </button>
      <button className={strike ? "on" : ""} onClick={() => onChange({ strike: !strike })} title="Strikethrough" aria-pressed={strike}>
        <Strikethrough size={14} />
      </button>
    </div>
  );
}

export function AlignControl({ value, onChange }: { value: Align; onChange: (value: Align) => void }) {
  const items: [Align, JSX.Element][] = [
    ["left", <AlignLeft size={14} key="l" />],
    ["center", <AlignCenter size={14} key="c" />],
    ["right", <AlignRight size={14} key="r" />],
    ["justify", <AlignJustify size={14} key="j" />],
  ];
  return (
    <div className="segmented" role="group" aria-label="Alignment">
      {items.map(([key, icon]) => (
        <button key={key} className={value === key ? "on" : ""} onClick={() => onChange(key)} title={`Align ${key}`}>
          {icon}
        </button>
      ))}
    </div>
  );
}

/** Properties for the text currently being edited in place. */
export function ActiveEditProps() {
  const edit = useEditor((s) => s.activeEdit);
  const patchDraft = useEditor((s) => s.patchDraft);
  const setActiveEdit = useEditor((s) => s.setActiveEdit);
  if (!edit) return null;
  const { draft, span } = edit;

  return (
    <>
      <div className="prop-section">
        <h4>{edit.mode === "block" ? "Paragraph" : "Text"}</h4>
        <div className="note">
          <div>
            Original font: <strong style={{ color: "var(--text)" }}>{span.font}</strong>
          </div>
          <div>
            {span.size} pt · {span.bold ? "bold" : "regular"}
            {span.italic ? " italic" : ""}
          </div>
        </div>
        <label className="field">
          <span>Font</span>
          <FontPicker
            value={draft.font}
            onChange={(font) => patchDraft({ font })}
            allowOriginal
            originalLabel={span.font}
            bold={draft.bold}
            italic={draft.italic}
          />
        </label>
        <div className="grid-2">
          <label className="field">
            <span>Size</span>
            <NumberField value={draft.size} min={1} max={500} step={0.5} suffix="pt" onChange={(size) => patchDraft({ size })} label="Font size" />
          </label>
          <label className="field">
            <span>Opacity</span>
            <NumberField
              value={Math.round(draft.opacity * 100)}
              min={5}
              max={100}
              step={5}
              suffix="%"
              onChange={(v) => patchDraft({ opacity: v / 100 })}
              label="Opacity"
            />
          </label>
        </div>
        <StyleToggles {...draft} onChange={patchDraft} />
        <label className="field">
          <span>Color</span>
          <ColorPicker value={draft.color} onChange={(color) => color && patchDraft({ color })} />
        </label>
      </div>
      {edit.mode === "block" ? (
        <div className="prop-section">
          <h4>Layout</h4>
          <AlignControl value={edit.align} onChange={(align) => setActiveEdit({ ...edit, align })} />
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>
            The paragraph reflows inside its original box. Press Ctrl+Enter to apply.
          </p>
        </div>
      ) : (
        <div className="prop-section">
          <h4>Spacing</h4>
          <div className="grid-2">
            <label className="field">
              <span>Letter spacing</span>
              <NumberField
                value={draft.charSpacing}
                placeholder="auto"
                min={-5}
                max={50}
                step={0.1}
                suffix="pt"
                onChange={(charSpacing) => patchDraft({ charSpacing })}
                label="Letter spacing"
              />
            </label>
            <label className="field">
              <span>Width scale</span>
              <NumberField value={draft.hscale} min={30} max={300} step={5} suffix="%" onChange={(hscale) => patchDraft({ hscale })} label="Horizontal scale" />
            </label>
          </div>
          <label className="check">
            <input type="checkbox" checked={draft.reflow} onChange={(e) => patchDraft({ reflow: e.target.checked })} />
            Shift the rest of the line to fit
          </label>
          <label className="check">
            <input type="checkbox" checked={draft.fitWidth} onChange={(e) => patchDraft({ fitWidth: e.target.checked })} />
            Squeeze/stretch to the original width
          </label>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>
            Drag the <strong>move</strong> handle to reposition. Enter applies, Esc cancels.
          </p>
        </div>
      )}
    </>
  );
}

/** Style used for newly added text. */
export function NewTextProps() {
  const style = useEditor((s) => s.newText);
  const patch = useEditor((s) => s.patchNewText);
  const value = style.faceId ? `face:${style.faceId}` : "face:";
  return (
    <div className="prop-section">
      <h4>New text</h4>
      <label className="field">
        <span>Font</span>
        <FontPicker
          value={value}
          onChange={(font) => font.startsWith("face:") && patch({ faceId: font.slice(5) || null })}
          bold={style.bold}
          italic={style.italic}
        />
      </label>
      <div className="grid-2">
        <label className="field">
          <span>Size</span>
          <NumberField value={style.size} min={2} max={500} step={1} suffix="pt" onChange={(size) => patch({ size })} label="Font size" />
        </label>
        <label className="field">
          <span>Line height</span>
          <NumberField value={style.lineHeight} min={0.6} max={4} step={0.1} onChange={(lineHeight) => patch({ lineHeight })} label="Line height" />
        </label>
      </div>
      <StyleToggles {...style} onChange={patch} />
      <AlignControl value={style.align} onChange={(align) => patch({ align })} />
      <label className="field">
        <span>Color</span>
        <ColorPicker value={style.color} onChange={(color) => color && patch({ color })} />
      </label>
      <label className="field">
        <span>Opacity {Math.round(style.opacity * 100)}%</span>
        <input className="range" type="range" min={5} max={100} value={style.opacity * 100} onChange={(e) => patch({ opacity: Number(e.target.value) / 100 })} />
      </label>
      <p className="muted" style={{ margin: 0, fontSize: 12 }}>
        Click on the page to type, or drag a box to wrap text at a fixed width. Ctrl+Enter adds it.
      </p>
    </div>
  );
}
