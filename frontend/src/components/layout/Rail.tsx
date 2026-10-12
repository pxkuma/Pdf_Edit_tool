import { BookMarked, CaseSensitive, FileText, History, LayoutGrid, PanelRightOpen, Search } from "lucide-react";
import type { ReactNode } from "react";
import { useEditor, type SidebarPanel } from "../../store/editor";

export function Rail() {
  const sidebar = useEditor((s) => s.sidebar);
  const setSidebar = useEditor((s) => s.setSidebar);
  const propertiesOpen = useEditor((s) => s.propertiesOpen);
  const toggleProperties = useEditor((s) => s.toggleProperties);

  const item = (key: Exclude<SidebarPanel, null>, icon: ReactNode, label: string) => (
    <button className={`icon-btn${sidebar === key ? " active" : ""}`} title={label} aria-label={label} onClick={() => setSidebar(key)}>
      {icon}
    </button>
  );

  return (
    <nav className="rail" aria-label="Panels">
      {item("thumbnails", <LayoutGrid size={18} />, "Pages")}
      {item("search", <Search size={18} />, "Find & replace (Ctrl+F)")}
      {item("outline", <BookMarked size={18} />, "Bookmarks")}
      {item("forms", <FileText size={18} />, "Form fields")}
      {item("fonts", <CaseSensitive size={18} />, "Document fonts")}
      {item("history", <History size={18} />, "History")}
      <span className="spacer" />
      {!propertiesOpen && (
        <button className="icon-btn" title="Show properties" aria-label="Show properties" onClick={toggleProperties}>
          <PanelRightOpen size={18} />
        </button>
      )}
    </nav>
  );
}
