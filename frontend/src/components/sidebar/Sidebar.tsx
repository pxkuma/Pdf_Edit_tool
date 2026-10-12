import { X } from "lucide-react";
import { useEditor, type SidebarPanel } from "../../store/editor";
import { FontsPanel } from "./FontsPanel";
import { FormsPanel } from "./FormsPanel";
import { HistoryPanel } from "./HistoryPanel";
import { OutlinePanel } from "./OutlinePanel";
import { SearchPanel } from "./SearchPanel";
import { Thumbnails } from "./Thumbnails";

const TITLES: Record<Exclude<SidebarPanel, null>, string> = {
  thumbnails: "Pages",
  outline: "Bookmarks",
  search: "Find & Replace",
  forms: "Form fields",
  history: "History",
  fonts: "Document fonts",
};

export function Sidebar() {
  const panel = useEditor((s) => s.sidebar);
  const setSidebar = useEditor((s) => s.setSidebar);
  if (!panel) return null;
  return (
    <aside className="sidebar" aria-label={TITLES[panel]}>
      <div className="panel-head">
        <h3>{TITLES[panel]}</h3>
        <button className="icon-btn small" onClick={() => setSidebar(panel)} aria-label="Close panel">
          <X size={15} />
        </button>
      </div>
      <div className="panel-body">
        {panel === "thumbnails" && <Thumbnails />}
        {panel === "outline" && <OutlinePanel />}
        {panel === "search" && <SearchPanel />}
        {panel === "forms" && <FormsPanel />}
        {panel === "history" && <HistoryPanel />}
        {panel === "fonts" && <FontsPanel />}
      </div>
    </aside>
  );
}
