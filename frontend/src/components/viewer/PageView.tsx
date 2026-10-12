import { Loader2 } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { PageInfo } from "../../api/types";
import { cssRect } from "../../lib/geometry";
import { usePageModel } from "../../lib/pageModel";
import { useEditor, type Tool } from "../../store/editor";
import { DrawLayer } from "./DrawLayer";
import { FormLayer } from "./FormLayer";
import { ObjectLayer } from "./ObjectLayer";
import { TextEditLayer } from "./TextEditLayer";
import { WordSelectLayer } from "./WordSelectLayer";

interface PageViewProps {
  docId: string;
  info: PageInfo;
  zoom: number;
  visible: boolean;
  tool: Tool;
  current: boolean;
}

const MARKUP_TOOLS = ["highlight", "underline", "strikeout", "squiggly"] as const;
type MarkupTool = (typeof MARKUP_TOOLS)[number];
const DRAW_TOOLS: Tool[] = [
  "ink", "rect", "ellipse", "line", "arrow", "note", "textbox", "image", "whiteout", "redact", "eraseText",
  "crop", "fieldText", "fieldCheckbox", "addText",
];

function renderScale(zoom: number): number {
  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  return Math.min(8, Math.max(0.125, Math.round(zoom * dpr * 8) / 8));
}

/** Keep showing the previous render until the new one has loaded (no white flash). */
function useBufferedImage(src: string, visible: boolean): string | null {
  const [shown, setShown] = useState<string | null>(visible ? src : null);
  useEffect(() => {
    if (!visible || src === shown) return;
    if (!shown) {
      setShown(src);
      return;
    }
    let alive = true;
    const img = new Image();
    img.onload = img.onerror = () => alive && setShown(src);
    img.src = src;
    return () => {
      alive = false;
    };
  }, [src, visible, shown]);
  return shown;
}

export const PageView = memo(function PageView({ docId, info, zoom, visible, tool, current }: PageViewProps) {
  const ref = useRef<HTMLDivElement>(null);
  const model = usePageModel(docId, info.index, info.token, visible);
  const hits = useEditor((s) => s.searchHits);
  const activeHit = useEditor((s) => s.activeHit);
  const setCurrentPage = useEditor((s) => s.setCurrentPage);
  const select = useEditor((s) => s.select);
  const width = info.width * zoom;
  const height = info.height * zoom;
  const pageHits = hits.map((hit, index) => ({ hit, index })).filter(({ hit }) => hit.page === info.index);

  const src = api.renderUrl(docId, info.index, renderScale(zoom), info.token);
  const shown = useBufferedImage(src, visible);

  const isMarkup = (MARKUP_TOOLS as readonly string[]).includes(tool);
  const layers = () => {
    if (!visible) return null;
    if (tool === "editText") return <TextEditLayer docId={docId} page={info.index} model={model} zoom={zoom} />;
    if (isMarkup) {
      return <WordSelectLayer docId={docId} page={info.index} model={model} zoom={zoom} markup={tool as MarkupTool} pageRef={ref} />;
    }
    if (DRAW_TOOLS.includes(tool)) {
      return <DrawLayer docId={docId} page={info.index} zoom={zoom} tool={tool} pageSize={[info.width, info.height]} pageRef={ref} />;
    }
    if (tool === "select") {
      return (
        <>
          <WordSelectLayer docId={docId} page={info.index} model={model} zoom={zoom} markup={null} pageRef={ref} />
          <ObjectLayer docId={docId} page={info.index} model={model} zoom={zoom} />
          <FormLayer docId={docId} model={model} zoom={zoom} />
        </>
      );
    }
    return null;
  };

  return (
    <div className="page-wrap" data-page={info.index} style={{ width, height }}>
      <span className="page-label">
        {info.index + 1}
        {info.label && info.label !== String(info.index + 1) ? ` · ${info.label}` : ""}
      </span>
      <div
        ref={ref}
        className={`page${current ? " current" : ""}`}
        style={{ width, height }}
        onPointerDownCapture={() => {
          if (!current) setCurrentPage(info.index);
        }}
        onPointerDown={() => tool === "select" && select(null)}
      >
        {visible && shown ? (
          <img
            className="render"
            src={shown}
            alt={`Page ${info.index + 1}`}
            draggable={false}
            decoding="async"
          />
        ) : null}
        {visible && !shown && (
          <div className="loading">
            <Loader2 className="spin" size={22} />
          </div>
        )}
        {pageHits.map(({ hit, index }) => (
          <div key={index} className={`search-hit${index === activeHit ? " active" : ""}`} style={cssRect(hit.rect, zoom)} />
        ))}
        {layers()}
      </div>
    </div>
  );
});
