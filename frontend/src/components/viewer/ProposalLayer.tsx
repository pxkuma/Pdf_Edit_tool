import { Check, X } from "lucide-react";
import { cssRect } from "../../lib/geometry";
import { KIND_LABEL } from "../../lib/formFields";
import { useEditor } from "../../store/editor";

/** Preview of recognised fields: click one to turn it off (or on again) before they are added. */
export function ProposalLayer({ page, zoom }: { page: number; zoom: number }) {
  const detected = useEditor((s) => s.detected);
  const toggle = useEditor((s) => s.toggleProposal);
  if (!detected) return null;
  return (
    <>
      {detected.proposals
        .filter((p) => p.page === page)
        .map((proposal) => {
          const off = detected.rejected.has(proposal.id);
          return (
            <button
              key={proposal.id}
              className={`proposal-box${off ? " off" : ""}`}
              style={cssRect(proposal.rect, zoom)}
              title={`${KIND_LABEL[proposal.kind]} “${proposal.name}” (${Math.round(proposal.confidence * 100)}%): click to ${off ? "include" : "skip"}`}
              aria-pressed={!off}
              aria-label={`${KIND_LABEL[proposal.kind]} ${proposal.name}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => toggle(proposal.id)}
            >
              <span className="proposal-mark">{off ? <X size={10} /> : <Check size={10} />}</span>
            </button>
          );
        })}
    </>
  );
}
