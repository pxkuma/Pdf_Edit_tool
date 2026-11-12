import { useEffect, useRef, useState } from "react";

interface CommentComposerProps {
  initial?: string;
  placeholder: string;
  submitLabel: string;
  /** Allow sending an empty text (clearing a comment). Replies need text. */
  allowEmpty?: boolean;
  /** Resolves to false when the server refused, so the text is kept for another try. */
  onSubmit: (text: string) => Promise<boolean>;
  onCancel: () => void;
}

/** A small text box with Send/Cancel. Ctrl+Enter sends, Escape cancels. */
export function CommentComposer({ initial = "", placeholder, submitLabel, allowEmpty = false, onSubmit, onCancel }: CommentComposerProps) {
  const [text, setText] = useState(initial);
  const [sending, setSending] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const canSend = !sending && (allowEmpty || text.trim().length > 0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    const sent = await onSubmit(text);
    setSending(false);
    if (!sent) ref.current?.focus();
  };

  return (
    <div className="composer">
      <textarea
        ref={ref}
        className="textarea"
        rows={3}
        value={text}
        maxLength={20000}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(e) => setText(e.target.value)}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation(); // typing must not trigger editor shortcuts
          if (e.key === "Escape") onCancel();
          else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send();
        }}
      />
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn small" onClick={onCancel}>
          Cancel
        </button>
        <button className="btn small primary" disabled={!canSend} onClick={() => void send()} title="Ctrl+Enter">
          {submitLabel}
        </button>
      </div>
    </div>
  );
}
