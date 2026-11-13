import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import { compareApi } from "../../api/compare";
import type { CompareChange, ComparePair } from "../../api/compareTypes";
import type { DocInfo } from "../../api/types";
import {
  COLUMN_GAP,
  PAD_X,
  PAD_TOP,
  ROW_GAP,
  allChanges,
  columnWidth,
  fitZoom,
  highlightsFor,
  pairTitle,
  renderScale,
  rowLayout,
  scrollTarget,
  visibleChanges,
  visibleRange,
} from "../../lib/compare";
import { useCompare } from "../../store/compare";
import { useEditor } from "../../store/editor";
import { ComparePageCell } from "./ComparePageCell";

interface RowProps {
  pair: ComparePair;
  height: number;
  columnWidth: number;
  zoom: number;
  visible: boolean;
  doc: DocInfo;
  sessionId: string;
  changes: CompareChange[];
  activeId: string | null;
}

function caption(side: "a" | "b", pair: ComparePair): string {
  const name = side === "a" ? "Original" : "Revised";
  const page = side === "a" ? pair.pageA : pair.pageB;
  return page === null ? name : `${name} · page ${page + 1}`;
}

const Row = memo(function Row({ pair, height, columnWidth: width, zoom, visible, doc, sessionId, changes, activeId }: RowProps) {
  const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio;
  const scale = renderScale(zoom, dpr);
  const slot: [number, number] = [Math.max(pair.sizeA?.[0] ?? 0, pair.sizeB?.[0] ?? 0), Math.max(pair.sizeA?.[1] ?? 0, pair.sizeB?.[1] ?? 0)];
  const info = pair.pageA === null ? undefined : doc.pages[pair.pageA];
  const srcA = visible && pair.pageA !== null && info ? api.renderUrl(doc.id, pair.pageA, scale, info.token) : null;
  const srcB = visible && pair.pageB !== null ? compareApi.renderUrl(doc.id, sessionId, pair.pageB, scale) : null;
  return (
    <section className={`cmp-row ${pair.status}`} style={{ height, marginBottom: ROW_GAP }} data-pair={pair.index} aria-label={pairTitle(pair)}>
      {(["a", "b"] as const).map((side) => (
        <div key={side} className="cmp-col" style={{ width }}>
          <div className="cmp-caption">{caption(side, pair)}</div>
          {visible && (
            <ComparePageCell
              size={side === "a" ? pair.sizeA : pair.sizeB}
              slotSize={slot}
              zoom={zoom}
              src={side === "a" ? srcA : srcB}
              label={`${side === "a" ? "Original" : "Revised"} ${pairTitle(pair)}`}
              empty={side === "a" ? "This page is not in the original" : "This page is not in the revised file"}
              highlights={highlightsFor(changes, side, activeId)}
            />
          )}
        </div>
      ))}
    </section>
  );
});

const MARGIN = 1200; // pixels around the viewport whose pages are already drawn

/** Both documents in one scroll area, one row per page pair, so scrolling and zooming stay in step. */
export function CompareRows() {
  const doc = useEditor((s) => s.doc);
  const report = useCompare((s) => s.report);
  const session = useCompare((s) => s.session);
  const filters = useCompare((s) => s.filters);
  const activeId = useCompare((s) => s.activeId);
  const jump = useCompare((s) => s.jump);
  const zoom = useCompare((s) => s.zoom);
  const fit = useCompare((s) => s.fit);
  const setZoom = useCompare((s) => s.setZoom);
  const ref = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ top: 0, height: 800, width: 1000 });
  const pairs = useMemo(() => report?.pairs ?? [], [report]);

  const layout = useMemo(() => rowLayout(pairs, zoom), [pairs, zoom]);
  const width = columnWidth(pairs, zoom);
  const shown = useMemo(() => visibleChanges(report, filters), [report, filters]);
  const byPair = useMemo(() => {
    const groups = new Map<number, CompareChange[]>();
    for (const change of shown) groups.set(change.pair, [...(groups.get(change.pair) ?? []), change]);
    return groups;
  }, [shown]);
  const [first, last] = visibleRange(layout, view.top, view.height, MARGIN);

  useLayoutEffect(() => {
    if (!fit || !pairs.length) return;
    const next = fitZoom(pairs, view.width);
    if (Math.abs(next - zoom) > 0.005) setZoom(next, true);
  }, [fit, pairs, view.width, zoom, setZoom]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setView((v) => ({ ...v, height: el.clientHeight, width: el.clientWidth }));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const el = ref.current;
    const target = jump && allChanges(report).find((change) => change.id === jump.id);
    if (el && target) el.scrollTo({ top: scrollTarget(layout, target, zoom, el.clientHeight), behavior: "smooth" });
    // Only a new request scrolls: changing the zoom afterwards must not pull the view back.
  }, [jump]);

  // Ctrl + wheel zooms and keeps the same part of the document in view.
  const keep = useRef<number | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && keep.current !== null) el.scrollTop = keep.current * layout.total;
    keep.current = null;
  }, [layout.total]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      keep.current = layout.total ? el.scrollTop / layout.total : 0;
      setZoom(useCompare.getState().zoom * Math.exp(-event.deltaY * 0.0022));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [layout.total, setZoom]);

  if (!doc || !session) return null;
  return (
    <div className="cmp-pages" ref={ref} onScroll={(e) => setView((v) => ({ ...v, top: e.currentTarget.scrollTop }))} tabIndex={-1}>
      <div className="cmp-canvas" style={{ width: width * 2 + COLUMN_GAP + PAD_X * 2, paddingTop: PAD_TOP, paddingLeft: PAD_X, paddingRight: PAD_X }}>
        {pairs.map((pair, index) => (
          <Row
            key={pair.index}
            pair={pair}
            height={layout.heights[index]}
            columnWidth={width}
            zoom={zoom}
            visible={index >= first && index <= last}
            doc={doc}
            sessionId={session.id}
            changes={byPair.get(pair.index) ?? NONE}
            activeId={activeId}
          />
        ))}
      </div>
    </div>
  );
}

const NONE: CompareChange[] = [];
