import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useEditor } from "../../store/editor";
import { PageView } from "./PageView";

const GAP = 18;
const PAD_TOP = 24;
const PAD_X = 32;

export function Viewer() {
  const doc = useEditor((s) => s.doc);
  const zoom = useEditor((s) => s.zoom);
  const fit = useEditor((s) => s.fit);
  const tool = useEditor((s) => s.tool);
  const currentPage = useEditor((s) => s.currentPage);
  const setZoom = useEditor((s) => s.setZoom);
  const setCurrentPage = useEditor((s) => s.setCurrentPage);
  const scrollRequest = useEditor((s) => s.scrollRequest);
  const ref = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ top: 0, height: 800, width: 1000 });
  const pages = doc?.pages ?? [];

  const offsets = useMemo(() => {
    const result: number[] = [];
    let y = PAD_TOP;
    for (const page of pages) {
      result.push(y);
      y += page.height * zoom + GAP;
    }
    return result;
  }, [pages, zoom]);

  // Fit-to-width / fit-to-page whenever the container or document changes.
  const applyFit = useCallback(() => {
    const el = ref.current;
    if (!el || !fit || !pages.length) return;
    const maxWidth = Math.max(...pages.map((p) => p.width));
    const page = pages[Math.min(currentPage, pages.length - 1)];
    const byWidth = (el.clientWidth - PAD_X * 2) / maxWidth;
    const byPage = Math.min(byWidth, (el.clientHeight - PAD_TOP * 2) / page.height);
    const next = Math.max(0.1, Math.min(6, fit === "width" ? Math.min(byWidth, 3) : byPage));
    if (Math.abs(next - zoom) > 0.005) setZoom(next, fit);
  }, [fit, pages, currentPage, zoom, setZoom]);

  useLayoutEffect(() => {
    applyFit();
  }, [applyFit]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      setViewport((v) => ({ ...v, height: el.clientHeight, width: el.clientWidth }));
      applyFit();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [applyFit]);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    setViewport({ top: el.scrollTop, height: el.clientHeight, width: el.clientWidth });
    const probe = el.scrollTop + el.clientHeight * 0.35;
    let index = 0;
    for (let i = 0; i < offsets.length; i++) if (offsets[i] <= probe) index = i;
    if (index !== useEditor.getState().currentPage) setCurrentPage(index);
  };

  // Keep the page under the cursor stable when zooming with ctrl+wheel.
  const anchor = useRef<{ page: number; ratio: number } | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    const saved = anchor.current;
    if (!el || !saved || !offsets.length) return;
    const page = pages[saved.page];
    if (page) el.scrollTop = offsets[saved.page] + page.height * zoom * saved.ratio - el.clientHeight * 0.35;
    anchor.current = null;
  }, [zoom, offsets, pages]);

  const rememberAnchor = () => {
    const el = ref.current;
    if (!el || !offsets.length) return;
    const probe = el.scrollTop + el.clientHeight * 0.35;
    const index = Math.max(0, offsets.findIndex((o, i) => probe >= o && (i === offsets.length - 1 || probe < offsets[i + 1])));
    const page = pages[index];
    anchor.current = { page: index, ratio: page ? (probe - offsets[index]) / (page.height * zoom) : 0 };
  };

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      rememberAnchor();
      const factor = Math.exp(-event.deltaY * 0.0022);
      setZoom(useEditor.getState().zoom * factor, null);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  useEffect(() => {
    if (!scrollRequest || !ref.current) return;
    const top = offsets[scrollRequest.page];
    if (top === undefined) return;
    const extra = scrollRequest.y !== undefined ? scrollRequest.y * zoom - ref.current.clientHeight * 0.3 : -PAD_TOP / 2;
    ref.current.scrollTo({ top: Math.max(0, top + extra), behavior: "smooth" });
  }, [scrollRequest]);

  // Hand tool: drag to pan.
  const pan = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const onPointerDown = (event: ReactPointerEvent) => {
    if (tool !== "pan" && event.button !== 1) return;
    const el = ref.current;
    if (!el) return;
    event.preventDefault();
    pan.current = { x: event.clientX, y: event.clientY, left: el.scrollLeft, top: el.scrollTop };
    el.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent) => {
    const el = ref.current;
    if (!pan.current || !el) return;
    el.scrollLeft = pan.current.left - (event.clientX - pan.current.x);
    el.scrollTop = pan.current.top - (event.clientY - pan.current.y);
  };
  const onPointerUp = () => {
    pan.current = null;
  };

  if (!doc) return null;
  const margin = viewport.height * 1.5;
  return (
    <div
      ref={ref}
      className={`viewer${tool === "pan" ? " panning" : ""}`}
      onScroll={onScroll}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      tabIndex={-1}
    >
      <div className="pages" style={{ gap: GAP, paddingTop: PAD_TOP }}>
        {pages.map((page, index) => {
          const top = offsets[index];
          const bottom = top + page.height * zoom;
          const visible = bottom > viewport.top - margin && top < viewport.top + viewport.height + margin;
          return (
            <PageView
              key={index}
              docId={doc.id}
              info={page}
              zoom={zoom}
              visible={visible}
              tool={tool}
              current={index === currentPage}
            />
          );
        })}
      </div>
    </div>
  );
}
