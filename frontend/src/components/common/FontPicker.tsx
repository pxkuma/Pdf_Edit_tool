import { ChevronDown, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type { DocFont } from "../../api/types";
import { findFace, useFonts, variantOf } from "../../lib/fonts";
import { pickFile } from "../../lib/files";
import { errorMessage, useEditor } from "../../store/editor";

interface FontPickerProps {
  value: string; // "original" | "face:<id>" | "doc:<xref>"
  onChange: (value: string) => void;
  allowOriginal?: boolean;
  originalLabel?: string;
  bold?: boolean;
  italic?: boolean;
}

const POPULAR = ["Liberation Sans", "Liberation Serif", "Liberation Mono", "Carlito", "Caladea", "DejaVu Sans", "DejaVu Serif", "Noto Sans", "Noto Serif", "Open Sans", "Lato", "Roboto"];

export function FontPicker({ value, onChange, allowOriginal, originalLabel, bold = false, italic = false }: FontPickerProps) {
  const { families, load } = useFonts();
  const docId = useEditor((s) => s.doc?.id);
  const version = useEditor((s) => s.doc?.version);
  const toast = useEditor((s) => s.toast);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [docFonts, setDocFonts] = useState<DocFont[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !docId) return;
    let alive = true;
    api.docFonts(docId).then((fonts) => alive && setDocFonts(fonts)).catch(() => alive && setDocFonts([]));
    return () => {
      alive = false;
    };
  }, [open, docId, version]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const label = useMemo(() => {
    if (value === "original") return originalLabel ? `${originalLabel} (original)` : "Original font";
    if (value.startsWith("doc:")) {
      const font = docFonts.find((f) => `doc:${f.xref}` === value);
      return font ? `${font.name} (document)` : "Document font";
    }
    const found = findFace(families, value.slice(5));
    return found ? `${found.family.family} ${found.face.style}` : "Default font";
  }, [value, docFonts, families, originalLabel]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q ? families.filter((f) => f.family.toLowerCase().includes(q)) : families;
    const popular = list.filter((f) => POPULAR.includes(f.family));
    const user = list.filter((f) => f.source === "user");
    const rest = list.filter((f) => !POPULAR.includes(f.family) && f.source !== "user");
    return { popular, user, rest };
  }, [families, query]);

  const choose = (next: string) => {
    onChange(next);
    setOpen(false);
    setQuery("");
  };

  const uploadFont = async () => {
    const file = await pickFile(".ttf,.otf,font/ttf,font/otf");
    if (!file) return;
    try {
      const face = await api.uploadFont(file);
      await load(true);
      toast(`Font "${face.family}" added`, "success");
      choose(`face:${face.id}`);
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  };

  const renderFamily = (family: (typeof families)[number]) => {
    const face = variantOf(family, bold, italic);
    const id = `face:${face.id}`;
    const on = value.startsWith("face:") && family.faces.some((f) => `face:${f.id}` === value);
    return (
      <button key={family.family} className={`font-option${on ? " on" : ""}`} onClick={() => choose(id)}>
        <span>{family.family}</span>
        <small>{family.mono ? "mono" : family.serif ? "serif" : "sans"}</small>
      </button>
    );
  };

  return (
    <div className="font-picker" ref={ref}>
      <button className="input small row between" onClick={() => setOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={open}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="font-list" role="listbox">
          <input
            className="input small"
            autoFocus
            placeholder="Search fonts…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ marginBottom: 4 }}
          />
          {allowOriginal && !query && (
            <>
              <div className="group">Keep original</div>
              <button className={`font-option${value === "original" ? " on" : ""}`} onClick={() => choose("original")}>
                <span>{originalLabel || "Original font"}</span>
                <small>exact match</small>
              </button>
            </>
          )}
          {docFonts.length > 0 && !query && (
            <>
              <div className="group">Fonts in this document</div>
              {docFonts.map((font) => (
                <button
                  key={font.xref}
                  className={`font-option${value === `doc:${font.xref}` ? " on" : ""}`}
                  onClick={() => choose(`doc:${font.xref}`)}
                  title={font.subset ? `Subset font: ${font.glyphs} characters available` : "Full font"}
                >
                  <span>{font.name}</span>
                  <small>{font.subset ? `subset · ${font.glyphs}` : font.type}</small>
                </button>
              ))}
            </>
          )}
          {filtered.user.length > 0 && <div className="group">Your fonts</div>}
          {filtered.user.map(renderFamily)}
          {filtered.popular.length > 0 && <div className="group">Popular</div>}
          {filtered.popular.map(renderFamily)}
          {filtered.rest.length > 0 && <div className="group">All installed fonts</div>}
          {filtered.rest.map(renderFamily)}
          <button className="font-option" onClick={uploadFont} style={{ color: "var(--accent)", fontSize: 13 }}>
            <span className="row">
              <Upload size={14} /> Upload a font (.ttf / .otf)
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
