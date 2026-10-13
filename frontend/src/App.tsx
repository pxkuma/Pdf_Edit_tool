import { useCallback, useEffect, useState } from "react";
import { api } from "./api/client";
import type { DocInfo } from "./api/types";
import { FontPrompt } from "./components/common/FontPrompt";
import { Toasts } from "./components/common/Toasts";
import { ExportDialog } from "./components/dialogs/ExportDialog";
import { InsertPagesDialog, MetadataDialog, ShortcutsDialog } from "./components/dialogs/MiscDialogs";
import { SignatureDialog, StampDialog } from "./components/dialogs/SignatureDialog";
import { HeaderFooterDialog, WatermarkDialog } from "./components/dialogs/StampDialogs";
import { Rail } from "./components/layout/Rail";
import { Ribbon, type RibbonTab } from "./components/layout/Ribbon";
import { TopBar } from "./components/layout/TopBar";
import { OcrDialog } from "./components/dialogs/OcrDialog";
import { PropertiesPanel } from "./components/properties/PropertiesPanel";
import { Sidebar } from "./components/sidebar/Sidebar";
import { StartScreen } from "./components/StartScreen";
import { Viewer } from "./components/viewer/Viewer";
import { useShortcuts } from "./hooks/useShortcuts";
import { flushEdit } from "./lib/editSession";
import { rememberDoc } from "./lib/files";
import { useFonts } from "./lib/fonts";
import { errorMessage, useEditor } from "./store/editor";

function docIdFromHash(): string | null {
  const match = /^#\/doc\/([a-f0-9]{32})$/.exec(window.location.hash);
  return match ? match[1] : null;
}

function Dialogs() {
  const dialog = useEditor((s) => s.dialog);
  switch (dialog) {
    case "export":
      return <ExportDialog />;
    case "protect":
      return <ExportDialog initialTab="protect" />;
    case "watermark":
      return <WatermarkDialog />;
    case "headerFooter":
      return <HeaderFooterDialog />;
    case "metadata":
      return <MetadataDialog />;
    case "signature":
      return <SignatureDialog />;
    case "stamp":
      return <StampDialog />;
    case "insertPages":
      return <InsertPagesDialog />;
    case "shortcuts":
      return <ShortcutsDialog />;
    case "ocr":
      return <OcrDialog />;
    default:
      return null;
  }
}

export default function App() {
  const doc = useEditor((s) => s.doc);
  const setDoc = useEditor((s) => s.setDoc);
  const toast = useEditor((s) => s.toast);
  const loadFonts = useFonts((s) => s.load);
  const [tab, setTab] = useState<RibbonTab>("edit");
  const [booting, setBooting] = useState(() => docIdFromHash() !== null);
  useShortcuts();

  useEffect(() => {
    loadFonts().catch((error: unknown) => toast(`Could not load fonts: ${errorMessage(error)}`, "error"));
  }, [loadFonts, toast]);

  const open = useCallback(
    (info: DocInfo) => {
      setDoc(info);
      useEditor.setState({ tool: "select", selectedPages: [], currentPage: 0, fit: "width", searchHits: [] });
      rememberDoc({ id: info.id, filename: info.filename, pages: info.pages.length, ts: Date.now() });
      if (window.location.hash !== `#/doc/${info.id}`) window.location.hash = `/doc/${info.id}`;
      document.title = `${info.filename} · PDF Studio`;
    },
    [setDoc],
  );

  // Restore the document referenced in the URL (survives page reloads).
  useEffect(() => {
    const id = docIdFromHash();
    if (!id) return;
    api
      .info(id)
      .then(open)
      .catch(() => {
        window.location.hash = "";
        toast("That document is no longer available. Please open it again.", "warning");
      })
      .finally(() => setBooting(false));
  }, [open, toast]);

  useEffect(() => {
    const onHash = () => {
      if (!docIdFromHash() && useEditor.getState().doc) {
        setDoc(null);
        document.title = "PDF Studio";
      }
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [setDoc]);

  const close = async () => {
    await flushEdit();
    setDoc(null);
    window.location.hash = "";
    document.title = "PDF Studio";
  };

  if (booting) return null;

  if (!doc) {
    return (
      <>
        <StartScreen onOpen={open} />
        <Toasts />
      </>
    );
  }

  return (
    <div className="app">
      <TopBar onClose={close} />
      <Ribbon tab={tab} onTab={setTab} />
      <div className="main">
        <Rail />
        <Sidebar />
        <Viewer />
        <PropertiesPanel />
      </div>
      <Dialogs />
      <FontPrompt />
      <Toasts />
    </div>
  );
}
