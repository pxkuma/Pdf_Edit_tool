import { AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, Italic, Strikethrough, Underline } from "lucide-react";
import { ColorPicker } from "../common/ColorPicker";
import { FontPicker } from "../common/FontPicker";
import { NumberField } from "../common/NumberField";
import { AUTO_BOX, DEFAULT_PUSH, useEditor, type PushDraft } from "../../store/editor";

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

function fmt(value: number, unit = ""): string {
  return `${Math.round(value * 100) / 100}${unit}`;
}

/** What the content stream says about the text being edited (kept exactly unless changed). */
function DetectedStyle() {
  const edit = useEditor((s) => s.activeEdit);
  if (!edit) return null;
  const { span } = edit;
  const rows: [string, string][] = [
    ["Font", span.ocr ? "Recognised by OCR" : span.font],
    ["Size", fmt(span.size, " pt")],
    ["Color", `${span.colorSpace} ${span.color}`],
    ["Rendering", span.render],
  ];
  if (Math.abs(span.hscale - 100) > 0.05 && !span.ocr) rows.push(["Width", fmt(span.hscale, "%")]);
  if (span.charSpacing) rows.push(["Letter spacing", fmt(span.charSpacing, " pt")]);
  if (span.wordSpacing) rows.push(["Word spacing", fmt(span.wordSpacing, " pt")]);
  if (span.rise) rows.push(["Baseline shift", fmt(span.rise, " pt")]);
  if (Math.abs(span.skew) > 0.01) rows.push(["Slant", fmt(span.skew * 100, "%")]);
  if (span.opacity < 0.999) rows.push(["Opacity", fmt(span.opacity * 100, "%")]);
  return (
    <div>
      <dl className="facts">
        {rows.map(([label, value]) => (
          <div key={label} style={{ display: "contents" }}>
            <dt>{label}</dt>
            <dd title={value}>{value}</dd>
          </div>
        ))}
      </dl>
      {span.exact && !span.ocr && (
        <p className="muted" style={{ margin: "6px 0 0", fontSize: 11 }}>
          Unchanged properties are written back exactly as in the original.
        </p>
      )}
    </div>
  );
}

/** Properties for the text currently being edited in place. */
export function ActiveEditProps() {
  const edit = useEditor((s) => s.activeEdit);
  const patchDraft = useEditor((s) => s.patchDraft);
  const patchEdit = useEditor((s) => s.patchEdit);
  if (!edit) return null;
  const { draft, span } = edit;

  return (
    <>
      <div className="prop-section">
        <h4>{edit.mode === "block" ? "Text box" : "Text"}</h4>
        <DetectedStyle />
        {span.ocr && edit.mode === "span" && (
          <div className="field">
            <span className="field-label">Scanned text</span>
            <label className="check">
              <input type="radio" name="ocrMode" checked={draft.ocrMode === "replace"} onChange={() => patchDraft({ ocrMode: "replace" })} />
              Replace in the image
            </label>
            <label className="check">
              <input type="radio" name="ocrMode" checked={draft.ocrMode === "hidden"} onChange={() => patchDraft({ ocrMode: "hidden" })} />
              Correct the hidden OCR text only
            </label>
          </div>
        )}
        <label className="field">
          <span>Font</span>
          <FontPicker
            value={span.ocr && draft.font === "original" ? "face:" : draft.font}
            onChange={(font) => patchDraft({ font })}
            allowOriginal={!span.ocr}
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
        <>
        <div className="prop-section">
          <h4>Layout</h4>
          <BoxGeometry />
          <AlignControl value={edit.align} onChange={(align) => patchEdit({ align })} />
          <label className="field">
            <span>Line spacing</span>
            <NumberField
              value={edit.lineHeight ?? null}
              placeholder="original"
              min={0.6}
              max={4}
              step={0.1}
              suffix="×"
              onChange={(lineHeight) => patchEdit({ lineHeight })}
              label="Line spacing"
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={(edit.box?.width ?? null) === null}
              onChange={(e) =>
                patchEdit({
                  box: {
                    dx: edit.box?.dx ?? 0,
                    dy: edit.box?.dy ?? 0,
                    width: e.target.checked ? null : (edit.blockBbox ?? span.bbox)[2] - (edit.blockBbox ?? span.bbox)[0],
                  },
                })
              }
            />
            Auto width: use free space before wrapping
          </label>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>
            Drag the border to move; it snaps to other text and the page centre (hold Alt to move freely).
            Alt+arrow keys nudge by 1 pt, Alt+Shift+arrows by 10 pt. Side handles set the width; corner handles
            resize the text. Ctrl+Enter applies, Esc cancels.
          </p>
        </div>
        <PushProps />
        </>
      ) : (
        <div className="prop-section">
          <h4>Spacing</h4>
          <div className="grid-2">
            <label className="field">
              <span>Letter spacing</span>
              <NumberField
                value={draft.charSpacing}
                placeholder={span.charSpacing !== null ? `${span.charSpacing} (original)` : "original"}
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

/** Exact position and width of the text box being edited (points). */
function BoxGeometry() {
  const edit = useEditor((s) => s.activeEdit);
  const patchEdit = useEditor((s) => s.patchEdit);
  if (!edit?.boxInfo) return null;
  const info = edit.boxInfo;
  const box = edit.box ?? AUTO_BOX;
  const original = edit.blockBbox ?? edit.span.bbox;
  return (
    <div className="grid-3">
      <label className="field">
        <span>X</span>
        <NumberField value={info.x} step={1} suffix="pt" label="Box left" onChange={(x) => patchEdit({ box: { ...box, dx: box.dx + x - info.x } })} />
      </label>
      <label className="field">
        <span>Y</span>
        <NumberField value={info.y} step={1} suffix="pt" label="Box top" onChange={(y) => patchEdit({ box: { ...box, dy: box.dy + y - info.y } })} />
      </label>
      <label className="field">
        <span>W</span>
        <NumberField
          value={info.width}
          min={12}
          step={1}
          suffix="pt"
          label="Box width"
          placeholder="auto"
          onChange={(width) => patchEdit({ box: { dx: info.x - original[0], dy: box.dy, width } })}
        />
      </label>
    </div>
  );
}

/** How content below a growing text box moves. */
function PushProps() {
  const edit = useEditor((s) => s.activeEdit);
  const patchEdit = useEditor((s) => s.patchEdit);
  if (!edit || edit.mode !== "block") return null;
  const push = edit.push ?? DEFAULT_PUSH;
  const info = edit.pushInfo;
  const set = (patch: Partial<PushDraft>) => patchEdit({ push: { ...push, ...patch } });
  const pinned = Object.keys(push.overrides).length;

  return (
    <div className="prop-section">
      <h4>Content below</h4>
      <label className="check">
        <input type="checkbox" checked={push.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
        Push content down when the box grows
      </label>
      {push.enabled && (
        <>
          <div className="segmented" role="group" aria-label="What moves">
            <button className={push.scope === "column" ? "on" : ""} onClick={() => set({ scope: "column" })} title="Only content in the box's column (and below it)">
              This column
            </button>
            <button className={push.scope === "page" ? "on" : ""} onClick={() => set({ scope: "page" })} title="Everything below the box, across the page">
              Full width
            </button>
          </div>
          <label className="check">
            <input type="checkbox" checked={push.follow} onChange={(e) => set({ follow: e.target.checked })} />
            Pull content up when the box gets shorter
          </label>
          <label className="field">
            <span>Extra spacing</span>
            <NumberField value={push.extra} min={-200} max={500} step={1} suffix="pt" onChange={(extra) => set({ extra })} label="Extra spacing" />
          </label>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>
            {info && info.count > 0
              ? `Moves ${info.count} item${info.count > 1 ? "s" : ""} ${info.dy > 0 ? "down" : "up"} ${Math.abs(info.dy).toFixed(1)} pt.`
              : "Nothing moves yet: the box hasn't grown."}{" "}
            Click an item on the page to keep it in place or move it too.
          </p>
          {info && info.offPage > 0 && (
            <p className="note warn" style={{ margin: 0 }}>
              {info.offPage} item{info.offPage > 1 ? "s" : ""} would move past the bottom of the page.
            </p>
          )}
          {info && info.conflicts > 0 && (
            <p className="note warn" style={{ margin: 0 }}>
              Moved content will overlap {info.conflicts} item{info.conflicts > 1 ? "s that stay" : " that stays"} (outlined in red). Click
              {info.conflicts > 1 ? " them" : " it"} to move {info.conflicts > 1 ? "them" : "it"} too, or switch to Full width.
            </p>
          )}
          {pinned > 0 && (
            <button className="link-btn" onClick={() => set({ overrides: {} })}>
              Reset {pinned} manual choice{pinned > 1 ? "s" : ""}
            </button>
          )}
        </>
      )}
    </div>
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
