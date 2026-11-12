import { Download, MessageSquarePlus, Upload, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { CommentStatus } from "../../api/types";
import {
  NO_FILTER,
  countLabel,
  filterComments,
  groupComments,
  isFiltering,
  nextNotePosition,
  presentTypes,
  sortComments,
  summarizeImport,
  type CommentFilter,
  type CommentSort,
} from "../../lib/comments";
import { pickFile, saveBlob } from "../../lib/files";
import { useEditor } from "../../store/editor";
import { CommentCard } from "./CommentCard";
import { CommentFilters } from "./CommentFilters";
import type { CommentActions, Item } from "./CommentItem";
import { useComments } from "./useComments";

export function CommentsPanel() {
  const doc = useEditor((s) => s.doc);
  const currentPage = useEditor((s) => s.currentPage);
  const author = useEditor((s) => s.commentAuthor);
  const active = useEditor((s) => s.activeComment);
  const { run, track, toast, focusComment, clearActiveComment, setCommentAuthor } = useEditor.getState();
  const { data, error } = useComments();
  const [filter, setFilter] = useState<CommentFilter>(NO_FILTER);
  const [sort, setSort] = useState<CommentSort>("page");
  const [startEditing, setStartEditing] = useState<number | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  useEffect(() => () => clearActiveComment(), [clearActiveComment]);

  const comments = data?.comments ?? [];
  useEffect(() => {
    // The new note's card has opened its editor by now (its effect runs first): forget the request.
    if (startEditing !== null && comments.some((c) => c.xref === startEditing)) setStartEditing(null);
  }, [startEditing, comments]);
  const visible = useMemo(() => sortComments(filterComments(comments, filter), sort), [comments, filter, sort]);
  const groups = useMemo(() => groupComments(visible, sort), [visible, sort]);
  const types = useMemo(() => presentTypes(comments), [comments]);

  if (!doc) return null;
  if (!data) return <div className="empty">{error ?? "Loading…"}</div>;

  const ok = (result: unknown) => result !== undefined; // run() answers undefined when the request failed

  const actions: CommentActions = {
    focus: (item) => focusComment(item.page, item.xref, item.rect[1]),
    edit: async (item, text) => ok(await run(() => api.editComment(doc.id, item.page, item.xref, { text }))),
    reply: async (item, text) => ok(await run(() => api.replyToComment(doc.id, item.page, item.xref, text, author), "Reply added")),
    remove: async (item: Item) => {
      const done = await run(() => api.deleteComment(doc.id, item.page, item.xref), "Comment deleted (Undo brings it back)");
      if (ok(done) && active?.xref === item.xref) clearActiveComment();
    },
    setStatus: async (item, status: CommentStatus) => {
      await run(() => api.setCommentStatus(doc.id, item.page, item.xref, { status, author }));
    },
    setChecked: async (item, checked) => {
      await run(() => api.setCommentStatus(doc.id, item.page, item.xref, { checked, author }));
    },
  };

  const addNote = async () => {
    const [x, y] = nextNotePosition(comments, currentPage);
    const created = await run(() => api.addComment(doc.id, { page: currentPage, kind: "note", point: [x, y], text: "", author }));
    if (!created) return;
    setFilter(NO_FILTER);
    setStartEditing(created.xref);
    focusComment(currentPage, created.xref, y);
  };

  const exportXfdf = async () => {
    const file = await track(() => api.exportXfdf(doc.id));
    if (file) saveBlob(file.blob, file.filename);
  };

  const importXfdf = async () => {
    const file = await pickFile(".xfdf,.xml,application/vnd.adobe.xfdf,text/xml");
    if (!file) return;
    const result = await run(() => api.importXfdf(doc.id, file));
    if (!result) return;
    setWarnings(result.warnings);
    toast(summarizeImport(result), result.skipped ? "warning" : "success");
  };

  return (
    <div className="comments">
      <label className="field">
        <span>Your name (signs your comments)</span>
        <input
          className="input small"
          value={author}
          maxLength={200}
          placeholder="Reviewer"
          onChange={(e) => setCommentAuthor(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
        />
      </label>
      <div className="row wrap" style={{ gap: 4 }}>
        <button className="btn small" onClick={() => void addNote()} title={`Add a note to page ${currentPage + 1}`}>
          <MessageSquarePlus size={14} /> Add note
        </button>
        <button className="btn small" onClick={() => void exportXfdf()} disabled={!data.count} title="Save all comments as an XFDF file">
          <Download size={14} /> Export
        </button>
        <button className="btn small" onClick={() => void importXfdf()} title="Merge the comments of an XFDF file into this document">
          <Upload size={14} /> Import
        </button>
      </div>

      {warnings.length > 0 && (
        <div className="note warn comment-notice" role="status">
          <button className="icon-btn small" aria-label="Dismiss" onClick={() => setWarnings([])}>
            <X size={13} />
          </button>
          <ul>
            {warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      {comments.length > 0 && (
        <>
          <CommentFilters filter={filter} sort={sort} authors={data.authors} types={types} onFilter={setFilter} onSort={setSort} />
          <div className="comment-count muted" aria-live="polite">
            {countLabel(visible.length, comments.length, data.count, isFiltering(filter))}
          </div>
        </>
      )}

      {comments.length === 0 && (
        <div className="empty">No comments yet. Add a note, or use the highlight, underline, strikeout and text box tools and the comment appears here.</div>
      )}
      {comments.length > 0 && visible.length === 0 && <div className="empty">No comments match the filters.</div>}

      {groups.map((group) => (
        <section key={group.key} className="comment-group" aria-label={group.title}>
          <h4>
            {group.title} <small>{group.comments.length}</small>
          </h4>
          {group.comments.map((comment) => (
            <CommentCard
              key={comment.xref}
              comment={comment}
              active={active?.page === comment.page && active.xref === comment.xref}
              startEditing={startEditing}
              actions={actions}
            />
          ))}
        </section>
      ))}
    </div>
  );
}
