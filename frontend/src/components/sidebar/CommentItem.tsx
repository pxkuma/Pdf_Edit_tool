import { Check, MessageSquareReply, Pencil, Trash2 } from "lucide-react";
import type { CommentReply, CommentStatus, PdfComment } from "../../api/types";
import { STATUSES, STATUS_LABEL, authorLabel, initials, relativeTime, typeLabel } from "../../lib/comments";
import { CommentComposer } from "./CommentComposer";
import { CommentTypeIcon } from "./CommentTypeIcon";

export type Item = PdfComment | CommentReply;

export interface CommentActions {
  focus: (item: Item) => void;
  edit: (item: Item, text: string) => Promise<boolean>;
  remove: (item: Item) => Promise<void>;
  reply: (item: Item, text: string) => Promise<boolean>;
  setStatus: (item: Item, status: CommentStatus) => Promise<void>;
  setChecked: (item: Item, checked: boolean) => Promise<void>;
}

interface CommentItemProps {
  item: Item;
  isReply: boolean;
  actions: CommentActions;
  editing: boolean;
  replying: boolean;
  onEditing: (editing: boolean) => void;
  onReplying: (replying: boolean) => void;
}

function hue(name: string): number {
  let value = 0;
  for (const ch of name) value = (value * 31 + ch.codePointAt(0)!) % 360;
  return value;
}

function Avatar({ name }: { name: string }) {
  const h = hue(name);
  return (
    <span className="avatar" style={{ background: `hsl(${h} 55% 90%)`, color: `hsl(${h} 50% 26%)` }} aria-hidden>
      {initials(name)}
    </span>
  );
}

function StatusSelect({ item, onChange }: { item: Item; onChange: (status: CommentStatus) => void }) {
  return (
    <select
      className={`select small status-select ${item.status}`}
      value={item.status}
      aria-label="Review status"
      title={item.statusBy ? `${STATUS_LABEL[item.status]} by ${item.statusBy}` : "Review status"}
      onChange={(e) => onChange(e.target.value as CommentStatus)}
      onClick={(e) => e.stopPropagation()}
    >
      {STATUSES.map((status) => (
        <option key={status} value={status}>
          {STATUS_LABEL[status]}
        </option>
      ))}
    </select>
  );
}

/** One comment, or one reply of a thread: who, when, what, and the things you can do with it. */
export function CommentItem({ item, isReply, actions, editing, replying, onEditing, onReplying }: CommentItemProps) {
  const author = authorLabel(item.author);
  const when = relativeTime(item.modified || item.created);
  const edited = item.created && item.modified && item.modified > item.created;

  return (
    <div className={`comment-item${isReply ? " reply" : ""}`} style={isReply ? { marginLeft: Math.min(((item as CommentReply).depth - 1) * 14, 42) } : undefined}>
      <div className="comment-head">
        <Avatar name={item.author} />
        <div className="comment-who">
          <strong title={author}>{author}</strong>
          <span className="muted">
            {when}
            {edited ? " · edited" : ""}
          </span>
        </div>
        {!isReply && (
          <span className="comment-type" title={typeLabel(item.type)}>
            <CommentTypeIcon type={item.type} />
          </span>
        )}
      </div>

      {!isReply && item.quote && <blockquote className="comment-quote">{item.quote}</blockquote>}

      {editing ? (
        <CommentComposer
          initial={item.contents}
          placeholder="Comment"
          submitLabel="Save"
          allowEmpty={!isReply}
          onSubmit={async (text) => {
            const saved = await actions.edit(item, text);
            if (saved) onEditing(false);
            return saved;
          }}
          onCancel={() => onEditing(false)}
        />
      ) : item.contents ? (
        <p className="comment-text">{item.contents}</p>
      ) : (
        !isReply && <p className="comment-text muted">{item.type === "Text" ? "Empty note" : "No comment text"}</p>
      )}

      {!editing && (
        <div className="comment-tools">
          <button className="btn ghost small" onClick={() => onReplying(!replying)} aria-expanded={replying}>
            <MessageSquareReply size={13} /> Reply
          </button>
          <button className="icon-btn small" title="Edit" aria-label="Edit" onClick={() => onEditing(true)}>
            <Pencil size={13} />
          </button>
          <button className="icon-btn small" title="Delete" aria-label="Delete" onClick={() => void actions.remove(item)}>
            <Trash2 size={13} />
          </button>
          <span className="spacer" />
          {!isReply && (
            <button
              className={`icon-btn small${item.checked ? " active" : ""}`}
              title={item.checked ? "Remove checkmark" : "Add checkmark"}
              aria-label="Checkmark"
              aria-pressed={item.checked}
              onClick={() => void actions.setChecked(item, !item.checked)}
            >
              <Check size={14} />
            </button>
          )}
          <StatusSelect item={item} onChange={(status) => void actions.setStatus(item, status)} />
        </div>
      )}

      {replying && (
        <CommentComposer
          placeholder="Write a reply"
          submitLabel="Reply"
          onSubmit={async (text) => {
            const sent = await actions.reply(item, text);
            if (sent) onReplying(false);
            return sent;
          }}
          onCancel={() => onReplying(false)}
        />
      )}
    </div>
  );
}
