import { useMemo } from "react";
import { countByFilter, visibleChanges, type FilterKey } from "../../lib/compare";
import { useCompare } from "../../store/compare";
import { ChangeList } from "./ChangeList";

const FILTERS: { key: FilterKey; label: string; title: string }[] = [
  { key: "text", label: "Text", title: "Added, deleted and replaced words" },
  { key: "image", label: "Image", title: "Pictures, graphics and layout that look different" },
  { key: "page", label: "Pages", title: "Added and removed pages, and pages of another size" },
];

/** The list of differences, with switches for the kinds to show. */
export function CompareSidebar() {
  const report = useCompare((s) => s.report);
  const filters = useCompare((s) => s.filters);
  const activeId = useCompare((s) => s.activeId);
  const toggleFilter = useCompare((s) => s.toggleFilter);
  const goTo = useCompare((s) => s.goTo);
  const shown = useMemo(() => visibleChanges(report, filters), [report, filters]);
  const counts = useMemo(() => countByFilter(report), [report]);
  const none = (report?.totals.changes ?? 0) === 0;

  return (
    <aside className="sidebar cmp-sidebar" aria-label="Differences">
      <div className="panel-head">
        <h3>Differences</h3>
      </div>
      <div className="cmp-filters" role="group" aria-label="Show differences of type">
        {FILTERS.map(({ key, label, title }) => (
          <button
            key={key}
            className={`cmp-chip${filters[key] ? " on" : ""}`}
            onClick={() => toggleFilter(key)}
            aria-pressed={filters[key]}
            title={title}
            disabled={!counts[key] && !filters[key]}
          >
            {label}
            <span>{counts[key]}</span>
          </button>
        ))}
      </div>
      <div className="panel-body cmp-list-body">
        <ChangeList
          changes={shown}
          activeId={activeId}
          onSelect={goTo}
          empty={none ? "The two documents have no differences." : "Nothing to show. Switch a type back on above."}
        />
      </div>
    </aside>
  );
}
