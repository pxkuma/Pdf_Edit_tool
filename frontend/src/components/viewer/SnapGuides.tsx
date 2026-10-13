import type { Guides } from "../../lib/snap";

/** Guide lines shown while a text box snaps (page points). */
export function SnapGuides({ guides, zoom }: { guides: Guides; zoom: number }) {
  return (
    <>
      {guides.x !== undefined && <div className="snap-guide v" style={{ left: guides.x * zoom }} />}
      {guides.y !== undefined && <div className="snap-guide h" style={{ top: guides.y * zoom }} />}
    </>
  );
}
