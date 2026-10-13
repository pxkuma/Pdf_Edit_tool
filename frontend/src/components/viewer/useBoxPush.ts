import { useEffect, useMemo, useRef } from "react";
import type { Rect } from "../../api/types";
import { boxGrowth, pushConflicts, selectPush, type PushCandidate } from "../../lib/push";
import { DEFAULT_PUSH, useEditor, type ActiveEdit } from "../../store/editor";

interface BoxPushInput {
  edit: ActiveEdit;
  original: Rect;
  columnX: [number, number];
  rows: number;
  step: number;
  candidates: PushCandidate[];
  pageSize: [number, number];
}

/** Content below a growing text box: what moves and by how much (see lib/push.ts). */
export function useBoxPush({ edit, original, columnX, rows, step, candidates, pageSize }: BoxPushInput) {
  const { span, draft } = edit;
  const patchEdit = useEditor((s) => s.patchEdit);
  const push = edit.push ?? DEFAULT_PUSH;
  const growth = boxGrowth({
    rows,
    lines: edit.lineCount ?? 1,
    step,
    originalStep: edit.lineStep ?? span.size * 1.2,
    size: draft.size,
    originalSize: span.size,
  });
  const dy = push.enabled ? Math.round(((push.follow ? growth : Math.max(0, growth)) + push.extra) * 100) / 100 : 0;
  const selection = useMemo(
    () => selectPush(candidates, original, columnX, push, { width: pageSize[0], height: pageSize[1] }),
    [candidates, original, columnX[0], columnX[1], push.scope, push.overrides, pageSize[0], pageSize[1]],
  );
  const conflicts = useMemo(() => pushConflicts(selection.moving, selection.kept, dy), [selection, dy]);
  const latest = useRef({ dy, items: selection.moving });
  latest.current = { dy, items: selection.moving };

  const offPage = selection.moving.filter((m) => m.bbox[3] + dy > pageSize[1]).length;
  const info =
    Math.abs(dy) < 0.05
      ? { count: 0, dy: 0, offPage: 0, conflicts: 0 }
      : { count: selection.moving.length, dy, offPage, conflicts: conflicts.length };
  useEffect(() => {
    const current = useEditor.getState().activeEdit?.pushInfo;
    if (!current || (Object.keys(info) as (keyof typeof info)[]).some((k) => current[k] !== info[k])) {
      patchEdit({ pushInfo: info });
    }
  });

  /** The request part sent on apply, or null when nothing moves. */
  const payload = () => {
    const { dy: shift, items } = latest.current;
    if (Math.abs(shift) < 0.05 || !items.length) return null;
    return { dy: shift, items: items.map((i) => ({ kind: i.kind, bbox: i.bbox, xref: i.xref ?? 0 })) };
  };

  const toggle = (item: PushCandidate, move: boolean) => {
    const current = useEditor.getState().activeEdit?.push ?? DEFAULT_PUSH;
    patchEdit({ push: { ...current, overrides: { ...current.overrides, [item.key]: move } } });
  };

  return { selection, conflicts, dy, payload, toggle };
}
