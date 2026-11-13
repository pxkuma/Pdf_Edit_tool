import { useEffect, useRef, useState } from "react";
import type { PdfComment } from "../../api/types";
import { CommentItem, type CommentActions, type Item } from "./CommentItem";

interface CommentCardProps {
  comment: PdfComment;
  active: boolean;
  /** xref of a comment that was just created and should open for editing. */
  startEditing: number | null;
  actions: CommentActions;
}

/** A comment with its replies. Clicking it points at the annotation on the page. */
export function CommentCard({ comment, active, startEditing, actions }: CommentCardProps) {
  const [editing, setEditing] = useState<number | null>(null);
  const [replying, setReplying] = useState<number | null>(null);
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (startEditing === comment.xref) {
      setEditing(comment.xref);
      ref.current?.scrollIntoView({ block: "nearest" });
    }
  }, [startEditing, comment.xref]);

  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const toggle = (state: number | null, set: (value: number | null) => void, item: Item) => (on: boolean) =>
    set(on ? item.xref : state === item.xref ? null : state);

  const onClick = (event: { target: EventTarget }) => {
    const target = event.target as HTMLElement;
    if (!target.closest("button, select, textarea, input, a")) actions.focus(comment);
  };

  return (
    <article
      ref={ref}
      className={`comment-card${active ? " active" : ""}${comment.status !== "none" ? ` is-${comment.status}` : ""}`}
      aria-label={`Comment by ${comment.author || "unknown author"}`}
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.target === e.currentTarget && e.key === "Enter" && actions.focus(comment)}
    >
      <CommentItem
        item={comment}
        isReply={false}
        actions={actions}
        editing={editing === comment.xref}
        replying={replying === comment.xref}
        onEditing={toggle(editing, setEditing, comment)}
        onReplying={toggle(replying, setReplying, comment)}
      />
      {comment.replies.map((reply) => (
        <CommentItem
          key={reply.xref}
          item={reply}
          isReply
          actions={actions}
          editing={editing === reply.xref}
          replying={replying === reply.xref}
          onEditing={toggle(editing, setEditing, reply)}
          onReplying={toggle(replying, setReplying, reply)}
        />
      ))}
    </article>
  );
}
