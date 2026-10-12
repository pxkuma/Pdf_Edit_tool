import { PanelRightClose } from "lucide-react";
import { useEditor, type DrawStyle, type Tool } from "../../store/editor";
import { ColorPicker } from "../common/ColorPicker";
import { NumberField } from "../common/NumberField";
import { SelectedObjectProps } from "./ObjectProps";
import { ActiveEditProps, NewTextProps } from "./TextProps";

const HINTS: Partial<Record<Tool, string>> = {
  select: "Select text to copy or mark it up. Click annotations or images to move, resize or style them. Fill form fields directly on the page.",
  pan: "Drag to scroll around the document.",
  editText: "Hover any text and click to edit it in its original font. Double-click to rewrite a whole paragraph.",
  whiteout: "Drag over an area to cover it with white and remove the text underneath.",
  eraseText: "Drag over text to delete it while keeping backgrounds and graphics.",
  redact: "Drag over an area to permanently remove everything underneath (text, images, graphics).",
  crop: "Drag a box to crop the page to that area.",
  note: "Click anywhere to place a sticky note.",
  textbox: "Drag a box (or click) to add a text comment.",
  image: "Click to place the image at its natural size, or drag a box to size it.",
  fieldText: "Drag a box to add a fillable text field.",
  fieldCheckbox: "Click to add a checkbox.",
};

function DrawStyleProps({ title, style, patch, fill }: { title: string; style: DrawStyle; patch: (p: Partial<DrawStyle>) => void; fill?: boolean }) {
  return (
    <div className="prop-section">
      <h4>{title}</h4>
      <label className="field">
        <span>Stroke</span>
        <ColorPicker value={style.color} onChange={(color) => color && patch({ color })} />
      </label>
      {fill && (
        <label className="field">
          <span>Fill</span>
          <ColorPicker value={style.fill} allowNone onChange={(f) => patch({ fill: f })} />
        </label>
      )}
      <div className="grid-2">
        <label className="field">
          <span>Width</span>
          <NumberField value={style.width} min={0.25} max={30} step={0.5} suffix="pt" onChange={(width) => patch({ width })} />
        </label>
        <label className="field">
          <span>Opacity</span>
          <NumberField value={Math.round(style.opacity * 100)} min={5} max={100} step={5} suffix="%" onChange={(v) => patch({ opacity: v / 100 })} />
        </label>
      </div>
      {fill && (
        <label className="check">
          <input type="checkbox" checked={style.dashed} onChange={(e) => patch({ dashed: e.target.checked })} /> Dashed line
        </label>
      )}
    </div>
  );
}

function ToolProps({ tool }: { tool: Tool }) {
  const { markup, patchMarkup, ink, patchInk, shape, patchShape, redactColor, setRedactColor } = useEditor();
  if (tool === "addText") return <NewTextProps />;
  if (["highlight", "underline", "strikeout", "squiggly"].includes(tool)) {
    return (
      <div className="prop-section">
        <h4>Markup</h4>
        <label className="field">
          <span>Color</span>
          <ColorPicker
            value={markup.color}
            onChange={(color) => color && patchMarkup({ color })}
            palette={["#ffd400", "#a3e635", "#22d3ee", "#f472b6", "#fb923c", "#e11d48", "#2563eb", "#000000"]}
          />
        </label>
        <label className="field">
          <span>Opacity {Math.round(markup.opacity * 100)}%</span>
          <input className="range" type="range" min={10} max={100} value={markup.opacity * 100} onChange={(e) => patchMarkup({ opacity: Number(e.target.value) / 100 })} />
        </label>
        <p className="muted" style={{ margin: 0, fontSize: 12 }}>Drag across words to mark them.</p>
      </div>
    );
  }
  if (tool === "ink") return <DrawStyleProps title="Pen" style={ink} patch={patchInk} />;
  if (["rect", "ellipse", "line", "arrow", "textbox"].includes(tool)) return <DrawStyleProps title="Shape" style={shape} patch={patchShape} fill />;
  if (tool === "redact") {
    return (
      <div className="prop-section">
        <h4>Redaction</h4>
        <label className="field">
          <span>Box color</span>
          <ColorPicker value={redactColor} onChange={(c) => c && setRedactColor(c)} palette={["#000000", "#ffffff", "#6b7280", "#e11d48"]} />
        </label>
        <p className="note warn" style={{ margin: 0 }}>{HINTS.redact}</p>
      </div>
    );
  }
  return null;
}

export function PropertiesPanel() {
  const { propertiesOpen, toggleProperties, tool, selection, activeEdit, doc, currentPage } = useEditor();
  if (!propertiesOpen || !doc) return null;
  const page = doc.pages[currentPage];
  const hint = HINTS[tool];

  return (
    <aside className="properties" aria-label="Properties">
      <div className="panel-head">
        <h3>Properties</h3>
        <button className="icon-btn small" onClick={toggleProperties} aria-label="Hide properties">
          <PanelRightClose size={15} />
        </button>
      </div>
      <div style={{ overflow: "auto", flex: 1 }}>
        {activeEdit ? (
          <ActiveEditProps />
        ) : selection ? (
          <SelectedObjectProps />
        ) : (
          <>
            <ToolProps tool={tool} />
            {hint && tool !== "redact" && (
              <div className="prop-empty">{hint}</div>
            )}
          </>
        )}
        {page && (
          <div className="prop-section">
            <h4>Page {currentPage + 1}</h4>
            <dl className="facts">
              <dt>Size</dt>
              <dd>
                {(page.width / 72 * 25.4).toFixed(0)} × {(page.height / 72 * 25.4).toFixed(0)} mm
              </dd>
              <dt>Points</dt>
              <dd>
                {Math.round(page.width)} × {Math.round(page.height)}
              </dd>
              <dt>Rotation</dt>
              <dd>{page.rotation}°</dd>
            </dl>
          </div>
        )}
      </div>
    </aside>
  );
}
