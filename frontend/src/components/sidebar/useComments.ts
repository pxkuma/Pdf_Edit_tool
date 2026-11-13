import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { CommentList } from "../../api/types";
import { errorMessage, useEditor } from "../../store/editor";

/**
 * The comments of the open document. They are read again whenever the document changes (an edit, an
 * undo, an import); until the new list arrives the previous one stays on screen.
 */
export function useComments(): { data: CommentList | null; error: string | null } {
  const docId = useEditor((s) => s.doc?.id);
  const version = useEditor((s) => s.doc?.version);
  const [loaded, setLoaded] = useState<{ docId: string; data: CommentList } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!docId) return;
    let alive = true;
    api
      .comments(docId)
      .then((data) => {
        if (!alive) return;
        setLoaded({ docId, data });
        setError(null);
      })
      .catch((failure: unknown) => alive && setError(errorMessage(failure)));
    return () => {
      alive = false;
    };
  }, [docId, version]);

  return { data: loaded && loaded.docId === docId ? loaded.data : null, error };
}
