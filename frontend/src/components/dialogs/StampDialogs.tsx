import { Droplets, Hash, Image as ImageIcon } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { pickFile } from "../../lib/files";
import { useEditor } from "../../store/editor";
import { ColorPicker } from "../common/ColorPicker";
import { FontPicker } from "../common/FontPicker";
import { Modal } from "../common/Modal";

export function WatermarkDialog() {
  const { doc, openDialog, run } = useEditor();
  const [mode, setMode] = useState<"text" | "image">("text");
  const [text, setText] = useState("CONFIDENTIAL");
  const [font, setFont] = useState("face:");
  const [size, setSize] = useState(60);
  const [color, setColor] = useState("#e11d48");
  const [opacity, setOpacity] = useState(0.25);
  const [angle, setAngle] = useState(45);
  const [layout, setLayout] = useState<"center" | "tile">("center");
  const [pages, setPages] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [scale, setScale] = useState(0.5);
  if (!doc) return null;
  const close = () => openDialog(null);

  const apply = async () => {
    close();
    if (mode === "image" && image) {
      await run(() => api.imageWatermark(doc.id, image, pages, scale, opacity), "Watermark added");
      return;
    }
    await run(
      () =>
        api.watermark(doc.id, {
          text,
          pages: pages || null,
          angle,
          layout,
          style: { font: font === "face:" ? "" : font, size, color, opacity, bold: true, italic: false },
        }),
      "Watermark added",
    );
  };

  return (
    <Modal
      title="Watermark"
      icon={<Droplets size={18} />}
      onClose={close}
      footer={
        <>
          <button className="btn" onClick={close}>Cancel</button>
          <button className="btn primary" onClick={apply} disabled={mode === "text" ? !text.trim() : !image}>
            Apply watermark
          </button>
        </>
      }
    >
      <div className="segmented">
        <button className={mode === "text" ? "on" : ""} onClick={() => setMode("text")}>Text</button>
        <button className={mode === "image" ? "on" : ""} onClick={() => setMode("image")}>Image</button>
      </div>
      {mode === "text" ? (
        <>
          <label className="field">
            <span>Text</span>
            <input className="input" value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <div className="grid-2">
            <label className="field">
              <span>Font</span>
              <FontPicker value={font} onChange={setFont} bold />
            </label>
            <label className="field">
              <span>Size: {size}pt</span>
              <input className="range" type="range" min={10} max={200} value={size} onChange={(e) => setSize(Number(e.target.value))} />
            </label>
            <label className="field">
              <span>Angle: {angle}°</span>
              <input className="range" type="range" min={-90} max={90} value={angle} onChange={(e) => setAngle(Number(e.target.value))} />
            </label>
            <label className="field">
              <span>Layout</span>
              <div className="segmented">
                <button className={layout === "center" ? "on" : ""} onClick={() => setLayout("center")}>Centered</button>
                <button className={layout === "tile" ? "on" : ""} onClick={() => setLayout("tile")}>Tiled</button>
              </div>
            </label>
          </div>
          <label className="field">
            <span>Color</span>
            <ColorPicker value={color} onChange={(c) => c && setColor(c)} />
          </label>
        </>
      ) : (
        <>
          <button className="btn" onClick={async () => setImage(await pickFile("image/*"))}>
            <ImageIcon size={15} /> {image ? image.name : "Choose image…"}
          </button>
          <label className="field">
            <span>Size: {Math.round(scale * 100)}% of page</span>
            <input className="range" type="range" min={5} max={100} value={scale * 100} onChange={(e) => setScale(Number(e.target.value) / 100)} />
          </label>
        </>
      )}
      <div className="grid-2">
        <label className="field">
          <span>Opacity: {Math.round(opacity * 100)}%</span>
          <input className="range" type="range" min={2} max={100} value={opacity * 100} onChange={(e) => setOpacity(Number(e.target.value) / 100)} />
        </label>
        <label className="field">
          <span>Pages</span>
          <input className="input" placeholder="All (e.g. 1-3,5)" value={pages} onChange={(e) => setPages(e.target.value)} />
        </label>
      </div>
    </Modal>
  );
}

export function HeaderFooterDialog() {
  const { doc, openDialog, run } = useEditor();
  const [template, setTemplate] = useState("Page {n} of {total}");
  const [position, setPosition] = useState("bottom-center");
  const [font, setFont] = useState("face:");
  const [size, setSize] = useState(10);
  const [color, setColor] = useState("#333333");
  const [margin, setMargin] = useState(28);
  const [pages, setPages] = useState("");
  const [start, setStart] = useState(1);
  if (!doc) return null;
  const close = () => openDialog(null);

  const apply = async () => {
    close();
    await run(
      () =>
        api.headerFooter(doc.id, {
          template,
          position,
          margin,
          pages: pages || null,
          start_number: start,
          style: { font: font === "face:" ? "" : font, size, color, opacity: 1, bold: false, italic: false },
        }),
      "Header/footer added",
    );
  };

  const positions = ["top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"];
  return (
    <Modal
      title="Page numbers, header & footer"
      icon={<Hash size={18} />}
      onClose={close}
      footer={
        <>
          <button className="btn" onClick={close}>Cancel</button>
          <button className="btn primary" onClick={apply} disabled={!template.trim()}>Apply</button>
        </>
      }
    >
      <label className="field">
        <span>Text — use {"{n}"}, {"{total}"}, {"{date}"}, {"{filename}"}</span>
        <input className="input" value={template} onChange={(e) => setTemplate(e.target.value)} />
      </label>
      <div className="row wrap">
        {["Page {n} of {total}", "{n}", "- {n} -", "{filename} · {date}"].map((preset) => (
          <button key={preset} className="btn small" onClick={() => setTemplate(preset)}>
            {preset}
          </button>
        ))}
      </div>
      <label className="field">
        <span>Position</span>
        <div className="grid-3">
          {positions.map((p) => (
            <button key={p} className={`btn small${position === p ? " primary" : ""}`} onClick={() => setPosition(p)}>
              {p.replace("-", " ")}
            </button>
          ))}
        </div>
      </label>
      <div className="grid-2">
        <label className="field">
          <span>Font</span>
          <FontPicker value={font} onChange={setFont} />
        </label>
        <label className="field">
          <span>Size (pt)</span>
          <input className="input" type="number" min={4} max={72} value={size} onChange={(e) => setSize(Number(e.target.value) || 10)} />
        </label>
        <label className="field">
          <span>Margin (pt)</span>
          <input className="input" type="number" min={0} max={200} value={margin} onChange={(e) => setMargin(Number(e.target.value) || 0)} />
        </label>
        <label className="field">
          <span>First number</span>
          <input className="input" type="number" min={0} value={start} onChange={(e) => setStart(Number(e.target.value) || 1)} />
        </label>
      </div>
      <label className="field">
        <span>Pages</span>
        <input className="input" placeholder="All (e.g. 2-)" value={pages} onChange={(e) => setPages(e.target.value)} />
      </label>
      <label className="field">
        <span>Color</span>
        <ColorPicker value={color} onChange={(c) => c && setColor(c)} />
      </label>
    </Modal>
  );
}
