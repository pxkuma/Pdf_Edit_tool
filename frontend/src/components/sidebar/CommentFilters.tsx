import { Search, X } from "lucide-react";
import type { CommentStatus } from "../../api/types";
import {
  NO_FILTER,
  SORT_LABEL,
  STATUSES,
  STATUS_LABEL,
  isFiltering,
  typeLabel,
  type CommentFilter,
  type CommentSort,
} from "../../lib/comments";

interface CommentFiltersProps {
  filter: CommentFilter;
  sort: CommentSort;
  authors: string[];
  types: string[];
  onFilter: (filter: CommentFilter) => void;
  onSort: (sort: CommentSort) => void;
}

export function CommentFilters({ filter, sort, authors, types, onFilter, onSort }: CommentFiltersProps) {
  const patch = (change: Partial<CommentFilter>) => onFilter({ ...filter, ...change });
  return (
    <div className="comment-filters">
      <div className="row" style={{ gap: 4 }}>
        <div className="comment-search">
          <Search size={13} aria-hidden />
          <input
            className="input small"
            type="search"
            placeholder="Search comments"
            aria-label="Search comments"
            value={filter.query}
            onChange={(e) => patch({ query: e.target.value })}
            onKeyDown={(e) => e.stopPropagation()}
          />
        </div>
        {isFiltering(filter) && (
          <button className="icon-btn small" title="Clear filters" aria-label="Clear filters" onClick={() => onFilter(NO_FILTER)}>
            <X size={14} />
          </button>
        )}
      </div>
      <div className="grid-2">
        <select className="select small" aria-label="Filter by author" value={filter.author} onChange={(e) => patch({ author: e.target.value })}>
          <option value="">All authors</option>
          {authors.map((author) => (
            <option key={author} value={author}>
              {author}
            </option>
          ))}
        </select>
        <select className="select small" aria-label="Filter by type" value={filter.type} onChange={(e) => patch({ type: e.target.value })}>
          <option value="">All types</option>
          {types.map((type) => (
            <option key={type} value={type}>
              {typeLabel(type)}
            </option>
          ))}
        </select>
        <select
          className="select small"
          aria-label="Filter by status"
          value={filter.status}
          onChange={(e) => patch({ status: e.target.value as CommentStatus | "all" })}
        >
          <option value="all">Any status</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABEL[status]}
            </option>
          ))}
        </select>
        <select className="select small" aria-label="Sort comments" value={sort} onChange={(e) => onSort(e.target.value as CommentSort)}>
          {(Object.keys(SORT_LABEL) as CommentSort[]).map((key) => (
            <option key={key} value={key}>
              Sort: {SORT_LABEL[key]}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
