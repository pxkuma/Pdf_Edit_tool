import type { PageModel } from "../../api/types";
import { cssRect } from "../../lib/geometry";
import { useEditor } from "../../store/editor";

interface CommentFocusProps {
  page: number;
  model: PageModel | null;
  zoom: number;
}

const MARGIN = 3; // points around the annotation

/** Rings the annotation of the comment chosen in the Comments panel. */
export function CommentFocus({ page, model, zoom }: CommentFocusProps) {
  // Only the page the comment is on re-renders when the choice changes.
  const active = useEditor((s) => (s.activeComment?.page === page ? s.activeComment : null));
  if (!active || !model) return null;
  const annotation = model.annotations.find((a) => a.xref === active.xref);
  if (!annotation) return null;
  const [x0, y0, x1, y1] = annotation.rect;
  // The nonce makes React start the flash again when the same comment is chosen twice.
  return <div key={active.nonce} className="comment-focus" style={cssRect([x0 - MARGIN, y0 - MARGIN, x1 + MARGIN, y1 + MARGIN], zoom)} aria-hidden />;
}
