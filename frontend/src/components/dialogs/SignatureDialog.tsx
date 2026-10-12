import "@fontsource/dancing-script/600.css";
import "@fontsource/great-vibes/400.css";
import { Eraser, Signature as SignatureIcon, Stamp, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { canvasToBlob, imageSize, pickFile, trimCanvas } from "../../lib/files";
import { errorMessage, useEditor } from "../../store/editor";
import { ColorPicker } from "../common/ColorPicker";
import { Modal } from "../common/Modal";

const SAVED_KEY = "pdfstudio.signatures";
const SCRIPT_FONTS = ["Dancing Script", "Great Vibes", "cursive"];

function loadSaved(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(SAVED_KEY) || "[]") as unknown;
    return Array.isArray(parsed) ? parsed.filter((s): s is string => typeof s === "string" && s.startsWith("data:image/png")) : [];
  } catch {
    return [];
  }
}

function saveSaved(list: string[]): void {
  try {
    localStorage.setItem(SAVED_KEY, JSON.stringify(list.slice(0, 8)));
  } catch {
    /* storage full or unavailable */
  }
}

async function dataUrlToBlob(url: string): Promise<Blob> {
  return (await fetch(url)).blob();
}

export function SignatureDialog() {
  const { openDialog, setPlacement, setTool, toast } = useEditor();
  const [mode, setMode] = useState<"draw" | "type" | "saved">(loadSaved().length ? "saved" : "draw");
  const [color, setColor] = useState("#1e3a8a");
  const [name, setName] = useState("");
  const [font, setFont] = useState(SCRIPT_FONTS[0]);
  const [saved, setSaved] = useState(loadSaved);
  const [remember, setRemember] = useState(true);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef<{ x: number; y: number } | null>(null);
  const [empty, setEmpty] = useState(true);
  const close = () => openDialog(null);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ratio = window.devicePixelRatio || 1;
    el.width = el.clientWidth * ratio * 2;
    el.height = el.clientHeight * ratio * 2;
    const ctx = el.getContext("2d");
    ctx?.scale(ratio * 2, ratio * 2);
    setEmpty(true);
  }, [mode]);

  const point = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const onDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    drawing.current = point(e);
  };

  const onMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const ctx = canvas.current?.getContext("2d");
    const last = drawing.current;
    if (!ctx || !last) return;
    const next = point(e);
    const pressure = e.pressure && e.pointerType === "pen" ? e.pressure : 0.6;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.4 + pressure * 2.4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(last.x, last.y);
    ctx.lineTo(next.x, next.y);
    ctx.stroke();
    drawing.current = next;
    setEmpty(false);
  };

  const clear = () => {
    const el = canvas.current;
    el?.getContext("2d")?.clearRect(0, 0, el.width, el.height);
    setEmpty(true);
  };

  const typedCanvas = async (): Promise<HTMLCanvasElement> => {
    await document.fonts.load(`64px "${font}"`);
    const el = document.createElement("canvas");
    el.width = 1400;
    el.height = 320;
    const ctx = el.getContext("2d");
    if (ctx) {
      ctx.font = `120px "${font}", cursive`;
      ctx.fillStyle = color;
      ctx.textBaseline = "middle";
      ctx.fillText(name, 30, 170);
    }
    return el;
  };

  const placePng = async (blob: Blob, label = "Signature") => {
    const size = await imageSize(blob);
    setPlacement({ blob, url: URL.createObjectURL(blob), ...size, label });
    setTool("image");
    close();
    toast("Click on the page to place it, or drag to size it.", "info");
  };

  const finish = async () => {
    try {
      const source = mode === "draw" ? canvas.current : await typedCanvas();
      if (!source) return;
      const trimmed = trimCanvas(source);
      if (remember) {
        const url = trimmed.toDataURL("image/png");
        const next = [url, ...saved.filter((s) => s !== url)];
        saveSaved(next);
      }
      await placePng(await canvasToBlob(trimmed));
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  };

  const upload = async () => {
    const file = await pickFile("image/*");
    if (file) await placePng(file);
  };

  const removeSaved = (url: string) => {
    const next = saved.filter((s) => s !== url);
    setSaved(next);
    saveSaved(next);
  };

  return (
    <Modal
      title="Signature"
      icon={<SignatureIcon size={18} />}
      onClose={close}
      wide
      footer={
        mode !== "saved" && (
          <>
            <label className="check" style={{ marginRight: "auto" }}>
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember on this device
            </label>
            <button className="btn" onClick={close}>Cancel</button>
            <button className="btn primary" disabled={mode === "draw" ? empty : !name.trim()} onClick={finish}>
              Place signature
            </button>
          </>
        )
      }
    >
      <div className="tabs">
        <button className={mode === "saved" ? "on" : ""} onClick={() => setMode("saved")}>Saved ({saved.length})</button>
        <button className={mode === "draw" ? "on" : ""} onClick={() => setMode("draw")}>Draw</button>
        <button className={mode === "type" ? "on" : ""} onClick={() => setMode("type")}>Type</button>
        <button onClick={upload}>
          <Upload size={13} /> Upload image
        </button>
      </div>
      {mode === "saved" &&
        (saved.length ? (
          <div className="sig-saved">
            {saved.map((url) => (
              <div key={url} style={{ position: "relative" }}>
                <button onClick={async () => placePng(await dataUrlToBlob(url))} title="Use this signature" style={{ width: "100%" }}>
                  <img src={url} alt="Saved signature" />
                </button>
                <button className="icon-btn small" style={{ position: "absolute", top: 2, right: 2 }} title="Remove" onClick={() => removeSaved(url)}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty">No saved signatures yet — draw or type one.</div>
        ))}
      {mode === "draw" && (
        <>
          <canvas ref={canvas} className="sig-pad" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => (drawing.current = null)} />
          <div className="row between">
            <ColorPicker value={color} onChange={(c) => c && setColor(c)} palette={["#000000", "#1e3a8a", "#2563eb", "#b91c1c"]} />
            <button className="btn small" onClick={clear}>
              <Eraser size={14} /> Clear
            </button>
          </div>
        </>
      )}
      {mode === "type" && (
        <>
          <input className="input" autoFocus placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="grid-3">
            {SCRIPT_FONTS.map((f) => (
              <button
                key={f}
                className={`btn${font === f ? " primary" : ""}`}
                style={{ height: 64, fontFamily: `"${f}", cursive`, fontSize: 26 }}
                onClick={() => setFont(f)}
              >
                {name || "Signature"}
              </button>
            ))}
          </div>
          <ColorPicker value={color} onChange={(c) => c && setColor(c)} palette={["#000000", "#1e3a8a", "#2563eb", "#b91c1c"]} />
        </>
      )}
    </Modal>
  );
}

const STAMPS: [string, string][] = [
  ["APPROVED", "#16a34a"],
  ["REJECTED", "#dc2626"],
  ["DRAFT", "#2563eb"],
  ["CONFIDENTIAL", "#dc2626"],
  ["FINAL", "#7c3aed"],
  ["PAID", "#16a34a"],
  ["RECEIVED", "#0891b2"],
  ["REVIEWED", "#d97706"],
  ["VOID", "#6b7280"],
];

export function StampDialog() {
  const { openDialog, setPlacement, setTool, toast } = useEditor();
  const [custom, setCustom] = useState("");
  const [color, setColor] = useState("#dc2626");
  const [withDate, setWithDate] = useState(true);
  const close = () => openDialog(null);

  const create = async (text: string, stampColor: string) => {
    const el = document.createElement("canvas");
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const fontSize = 72;
    ctx.font = `800 ${fontSize}px Inter, Arial, sans-serif`;
    const dateLine = withDate ? new Date().toLocaleDateString() : "";
    const width = Math.max(ctx.measureText(text).width, dateLine ? ctx.measureText(dateLine).width * 0.45 : 0) + 80;
    const height = dateLine ? 190 : 140;
    el.width = width;
    el.height = height;
    ctx.strokeStyle = stampColor;
    ctx.fillStyle = stampColor;
    ctx.lineWidth = 9;
    ctx.beginPath();
    ctx.roundRect(8, 8, width - 16, height - 16, 22);
    ctx.stroke();
    ctx.font = `800 ${fontSize}px Inter, Arial, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, width / 2, dateLine ? 80 : height / 2 + 4);
    if (dateLine) {
      ctx.font = `600 32px Inter, Arial, sans-serif`;
      ctx.fillText(dateLine, width / 2, 145);
    }
    const blob = await canvasToBlob(el);
    setPlacement({ blob, url: URL.createObjectURL(blob), width: width / 2.2, height: height / 2.2, label: "Stamp" });
    setTool("image");
    close();
    toast("Click on the page to place the stamp.", "info");
  };

  return (
    <Modal title="Stamps" icon={<Stamp size={18} />} onClose={close}>
      <div className="grid-3">
        {STAMPS.map(([text, c]) => (
          <button key={text} className="btn" style={{ color: c, borderColor: c, fontWeight: 800, letterSpacing: "0.05em" }} onClick={() => create(text, c)}>
            {text}
          </button>
        ))}
      </div>
      <label className="check">
        <input type="checkbox" checked={withDate} onChange={(e) => setWithDate(e.target.checked)} /> Include today's date
      </label>
      <div className="note">
        <strong style={{ color: "var(--text)" }}>Custom stamp</strong>
        <div className="row" style={{ marginTop: 8 }}>
          <input className="input small" placeholder="Stamp text" value={custom} onChange={(e) => setCustom(e.target.value.toUpperCase())} />
          <button className="btn small primary" disabled={!custom.trim()} onClick={() => create(custom.trim(), color)}>
            Create
          </button>
        </div>
        <div style={{ marginTop: 8 }}>
          <ColorPicker value={color} onChange={(c) => c && setColor(c)} />
        </div>
      </div>
    </Modal>
  );
}
