import { ShieldAlert } from "lucide-react";
import { useEditor } from "../../store/editor";
import { Modal } from "../common/Modal";

/** Asked once before the first edit of a signed document (and again after each new signature). */
export function SignedEditPrompt() {
  const pending = useEditor((s) => s.signedEditPrompt);
  const count = useEditor((s) => s.doc?.signatures ?? 0);
  const answer = useEditor((s) => s.answerSignedEdit);
  if (!pending) return null;
  const cancel = () => answer(false);
  return (
    <Modal
      title="This document is signed"
      icon={<ShieldAlert size={18} />}
      onClose={cancel}
      footer={
        <>
          <button className="btn primary" autoFocus onClick={cancel}>
            Keep it unchanged
          </button>
          <button className="btn danger" onClick={() => answer(true)}>
            Edit anyway
          </button>
        </>
      }
    >
      <p>
        It carries {count === 1 ? "a digital signature" : `${count} digital signatures`}. Changing it means the{" "}
        {count === 1 ? "signature no longer covers" : "signatures no longer cover"} the document you share: validation will report the
        changes, and edits that rewrite page content (such as text edits and redaction) break the {count === 1 ? "signature" : "signatures"}{" "}
        entirely.
      </p>
      <p className="sig-muted">Undo or History brings back the signed version. Adding another signature does not count as an edit.</p>
    </Modal>
  );
}
