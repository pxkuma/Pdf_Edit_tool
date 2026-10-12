import { ChevronDown, ChevronUp, Eraser, Replace, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { useEditor } from "../../store/editor";

export function SearchPanel() {
  const { doc, searchHits, activeHit, setSearch, setActiveHit, scrollTo, run, track, toast } = useEditor();
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [matchCase, setMatchCase] = useState(false);
  const [wholeWord, setWholeWord] = useState(false);
  const [showReplace, setShowReplace] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    return () => setSearch([]);
  }, [setSearch]);

  if (!doc) return null;

  const search = async (q = query) => {
    if (!q.trim()) {
      setSearch([]);
      return;
    }
    const hits = await track(() => api.search(doc.id, q));
    if (!hits) return;
    setSearch(hits);
    if (hits.length) scrollTo(hits[0].page, hits[0].rect[1]);
    else toast(`No matches for “${q}”`, "info");
  };

  const go = (delta: number) => {
    if (!searchHits.length) return;
    const next = (activeHit + delta + searchHits.length) % searchHits.length;
    setActiveHit(next);
    scrollTo(searchHits[next].page, searchHits[next].rect[1]);
  };

  const replaceAll = async () => {
    const result = await run(() =>
      api.replace(doc.id, { query, replacement, match_case: matchCase, whole_word: wholeWord }),
    );
    if (!result) return;
    const skipped = result.skipped ? ` (${result.skipped} could not be replaced because they span several styles)` : "";
    toast(`Replaced ${result.replaced} occurrence(s)${skipped}`, result.replaced ? "success" : "warning");
    setSearch([]);
  };

  const redactAll = async () => {
    const result = await run(() => api.redactSearch(doc.id, query, "", "#000000"));
    if (result) toast(`Redacted ${result.redacted} occurrence(s)`, "success");
    setSearch([]);
  };

  const pagesWithHits = new Map<number, number>();
  searchHits.forEach((hit) => pagesWithHits.set(hit.page, (pagesWithHits.get(hit.page) ?? 0) + 1));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <input ref={inputRef} className="input small" placeholder="Find in document…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="icon-btn small" type="submit" title="Search">
          <Search size={15} />
        </button>
      </form>
      <div className="row between">
        <span className="muted">{searchHits.length ? `${activeHit + 1} of ${searchHits.length}` : "No results"}</span>
        <div className="row" style={{ gap: 2 }}>
          <button className="icon-btn small" onClick={() => go(-1)} disabled={!searchHits.length} title="Previous">
            <ChevronUp size={15} />
          </button>
          <button className="icon-btn small" onClick={() => go(1)} disabled={!searchHits.length} title="Next">
            <ChevronDown size={15} />
          </button>
        </div>
      </div>
      <button className="btn small ghost" onClick={() => setShowReplace((v) => !v)} style={{ justifyContent: "flex-start" }}>
        <Replace size={14} /> {showReplace ? "Hide replace" : "Replace text…"}
      </button>
      {showReplace && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <input className="input small" placeholder="Replace with…" value={replacement} onChange={(e) => setReplacement(e.target.value)} />
          <label className="check">
            <input type="checkbox" checked={matchCase} onChange={(e) => setMatchCase(e.target.checked)} /> Match case
          </label>
          <label className="check">
            <input type="checkbox" checked={wholeWord} onChange={(e) => setWholeWord(e.target.checked)} /> Whole words
          </label>
          <button className="btn small primary" disabled={!query.trim()} onClick={replaceAll}>
            <Replace size={14} /> Replace all (keeps original font)
          </button>
        </div>
      )}
      <button className="btn small danger" disabled={!query.trim()} onClick={redactAll} title="Permanently remove every match">
        <Eraser size={14} /> Redact all matches
      </button>
      {pagesWithHits.size > 0 && (
        <div className="list" style={{ marginTop: 6 }}>
          {[...pagesWithHits.entries()].map(([page, count]) => (
            <button
              key={page}
              className="list-item"
              onClick={() => {
                const index = searchHits.findIndex((h) => h.page === page);
                setActiveHit(index);
                scrollTo(page, searchHits[index].rect[1]);
              }}
            >
              Page {page + 1}
              <small>{count} match{count > 1 ? "es" : ""}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
