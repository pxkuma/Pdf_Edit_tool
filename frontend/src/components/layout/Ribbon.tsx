import {
  ArrowUpRight,
  BookMarked,
  Calendar,
  Check,
  CheckSquare,
  Circle,
  Copy,
  Crop,
  Droplets,
  Eraser,
  FileImage,
  FileInput,
  FileOutput,
  FilePlus2,
  FileSearch,
  FileText,
  Hand,
  Highlighter,
  History,
  ImagePlus,
  Info,
  Layers,
  Lock,
  Maximize,
  MessageSquare,
  MessageSquareText,
  Minus,
  MousePointer2,
  Pencil,
  PenTool,
  Replace,
  RectangleHorizontal,
  ScanText,
  RotateCcw,
  RotateCw,
  Scissors,
  Signature,
  Square,
  Stamp,
  Strikethrough,
  TextCursorInput,
  Trash2,
  Type,
  Underline,
  Waves,
  X,
  Hash,
  ShieldOff,
  SquareDashedMousePointer,
  CaseSensitive,
} from "lucide-react";
import type { ReactNode } from "react";
import { api } from "../../api/client";
import { flushEdit } from "../../lib/editSession";
import { imageSize, pickFile } from "../../lib/files";
import { errorMessage, useEditor, type Tool } from "../../store/editor";

export type RibbonTab = "edit" | "annotate" | "sign" | "pages" | "protect" | "tools";

const TABS: [RibbonTab, string][] = [
  ["edit", "Edit"],
  ["annotate", "Comment"],
  ["sign", "Fill & Sign"],
  ["pages", "Pages"],
  ["protect", "Protect"],
  ["tools", "Tools"],
];

interface ToolButtonProps {
  icon: ReactNode;
  label: string;
  title?: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}

function ToolButton({ icon, label, title, active, disabled, onClick }: ToolButtonProps) {
  return (
    <button className={`tool-btn${active ? " active" : ""}`} onClick={onClick} title={title ?? label} disabled={disabled} aria-pressed={active}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

function Group({ children }: { children: ReactNode }) {
  return <div className="ribbon-group">{children}</div>;
}

export function Ribbon({ tab, onTab }: { tab: RibbonTab; onTab: (tab: RibbonTab) => void }) {
  return (
    <div className="ribbon-wrap">
      <nav className="ribbon-tabs" aria-label="Toolbars">
        {TABS.map(([key, label]) => (
          <button key={key} className={tab === key ? "on" : ""} onClick={() => onTab(key)}>
            {label}
          </button>
        ))}
      </nav>
      <Tools tab={tab} />
    </div>
  );
}

function Tools({ tab }: { tab: RibbonTab }) {
  const state = useEditor();
  const { doc, tool, setTool, run, openDialog, setSidebar, sidebar, toast, selectedPages, currentPage, setPlacement, setTextPreset } = state;
  if (!doc) return null;
  const targets = selectedPages.length ? selectedPages : [currentPage];
  const scope = targets.length > 1 ? `${targets.length} pages` : `page ${targets[0] + 1}`;

  const choose = async (next: Tool) => {
    await flushEdit();
    if (next === "addText") setTextPreset(null);
    setTool(tool === next && next !== "select" ? "select" : next);
  };

  const t = (key: Tool, icon: ReactNode, label: string, title?: string) => (
    <ToolButton key={key} icon={icon} label={label} title={title} active={tool === key} onClick={() => void choose(key)} />
  );

  const placeImage = async () => {
    const file = await pickFile("image/png,image/jpeg,image/gif,image/webp,image/bmp,image/tiff");
    if (!file) return;
    try {
      const size = await imageSize(file);
      setPlacement({ blob: file, url: URL.createObjectURL(file), ...size, label: "Image" });
      setTool("image");
      toast("Click on a page to place the image, or drag to size it.", "info");
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  };

  const preset = async (text: string) => {
    await flushEdit();
    setTextPreset(text);
    setTool("addText");
    toast("Click where the text should go.", "info");
  };

  const panel = (key: Parameters<typeof setSidebar>[0], icon: ReactNode, label: string) => (
    <ToolButton icon={icon} label={label} active={sidebar === key} onClick={() => setSidebar(key)} />
  );

  const pagesAction = (fn: () => Promise<unknown>) => async () => {
    await flushEdit();
    await fn();
  };

  switch (tab) {
    case "edit":
      return (
        <div className="ribbon" role="toolbar" aria-label="Edit tools">
          <Group>
            {t("select", <MousePointer2 size={18} />, "Select", "Select (V)")}
            {t("pan", <Hand size={18} />, "Pan", "Pan (Space)")}
          </Group>
          <Group>
            {t("editText", <Pencil size={18} />, "Edit text", "Edit existing text (T)")}
            {t("addText", <Type size={18} />, "Add text", "Add new text (A)")}
            <ToolButton icon={<ImagePlus size={18} />} label="Image" active={tool === "image"} onClick={placeImage} />
          </Group>
          <Group>
            {t("whiteout", <RectangleHorizontal size={18} />, "Whiteout", "Cover an area with white")}
            {t("eraseText", <Eraser size={18} />, "Erase text", "Remove text, keep background")}
          </Group>
          <Group>
            <ToolButton icon={<ScanText size={18} />} label="OCR" title="Recognise text in scanned pages" onClick={() => openDialog("ocr")} />
          </Group>
          <Group>
            {panel("search", <Replace size={18} />, "Find/Replace")}
            {panel("fonts", <CaseSensitive size={18} />, "Fonts")}
            {panel("history", <History size={18} />, "History")}
          </Group>
        </div>
      );
    case "annotate":
      return (
        <div className="ribbon" role="toolbar" aria-label="Annotation tools">
          <Group>
            {t("select", <MousePointer2 size={18} />, "Select")}
          </Group>
          <Group>
            {t("highlight", <Highlighter size={18} />, "Highlight", "Highlight (H)")}
            {t("underline", <Underline size={18} />, "Underline")}
            {t("strikeout", <Strikethrough size={18} />, "Strike")}
            {t("squiggly", <Waves size={18} />, "Squiggly")}
          </Group>
          <Group>
            {t("ink", <PenTool size={18} />, "Draw", "Freehand drawing (D)")}
            {t("rect", <Square size={18} />, "Rectangle")}
            {t("ellipse", <Circle size={18} />, "Ellipse")}
            {t("line", <Minus size={18} />, "Line")}
            {t("arrow", <ArrowUpRight size={18} />, "Arrow")}
          </Group>
          <Group>
            {t("note", <MessageSquare size={18} />, "Note", "Sticky note (N)")}
            {t("textbox", <MessageSquareText size={18} />, "Text box")}
            <ToolButton icon={<Stamp size={18} />} label="Stamp" onClick={() => openDialog("stamp")} />
          </Group>
          <Group>
            <ToolButton
              icon={<Layers size={18} />}
              label="Flatten"
              title="Burn annotations into the page content"
              onClick={pagesAction(() => run(() => api.flatten(doc.id, true, false), "Annotations flattened"))}
            />
          </Group>
        </div>
      );
    case "sign":
      return (
        <div className="ribbon" role="toolbar" aria-label="Fill and sign tools">
          <Group>
            {t("select", <MousePointer2 size={18} />, "Fill")}
            <ToolButton icon={<Signature size={18} />} label="Signature" onClick={() => openDialog("signature")} />
            {t("addText", <Type size={18} />, "Text")}
            <ToolButton icon={<Calendar size={18} />} label="Date" onClick={() => preset(new Date().toLocaleDateString())} />
            <ToolButton icon={<Check size={18} />} label="Check" onClick={() => preset("✓")} />
            <ToolButton icon={<X size={18} />} label="Cross" onClick={() => preset("✗")} />
          </Group>
          <Group>
            {t("fieldText", <TextCursorInput size={18} />, "Text field")}
            {t("fieldCheckbox", <CheckSquare size={18} />, "Checkbox")}
            {panel("forms", <FileText size={18} />, "All fields")}
          </Group>
          <Group>
            <ToolButton
              icon={<Layers size={18} />}
              label="Flatten form"
              onClick={pagesAction(() => run(() => api.flatten(doc.id, false, true), "Form flattened"))}
            />
          </Group>
        </div>
      );
    case "pages":
      return (
        <div className="ribbon" role="toolbar" aria-label="Page tools">
          <Group>
            <ToolButton icon={<RotateCcw size={18} />} label="Rotate left" title={`Rotate ${scope} left`} onClick={pagesAction(() => run(() => api.rotatePages(doc.id, targets, -90)))} />
            <ToolButton icon={<RotateCw size={18} />} label="Rotate right" title={`Rotate ${scope} right`} onClick={pagesAction(() => run(() => api.rotatePages(doc.id, targets, 90)))} />
          </Group>
          <Group>
            <ToolButton icon={<FilePlus2 size={18} />} label="Insert" title="Insert blank pages or another file" onClick={() => openDialog("insertPages")} />
            <ToolButton icon={<Copy size={18} />} label="Duplicate" title={`Duplicate ${scope}`} onClick={pagesAction(() => run(() => api.duplicatePages(doc.id, targets), "Duplicated"))} />
            <ToolButton
              icon={<Trash2 size={18} />}
              label="Delete"
              title={`Delete ${scope}`}
              disabled={targets.length >= doc.pages.length}
              onClick={pagesAction(() => run(() => api.deletePages(doc.id, targets), "Deleted"))}
            />
          </Group>
          <Group>
            {t("crop", <Crop size={18} />, "Crop")}
            <ToolButton icon={<Maximize size={18} />} label="Uncrop" title={`Reset crop of ${scope}`} onClick={pagesAction(() => run(() => api.resetCrop(doc.id, targets)))} />
          </Group>
          <Group>
            <ToolButton icon={<FileOutput size={18} />} label="Extract" title="Save pages as a new PDF" onClick={() => openDialog("export")} />
            <ToolButton icon={<Scissors size={18} />} label="Split" onClick={() => openDialog("export")} />
            {panel("thumbnails", <FileInput size={18} />, "Organize")}
          </Group>
        </div>
      );
    case "protect":
      return (
        <div className="ribbon" role="toolbar" aria-label="Protection tools">
          <Group>
            {t("redact", <SquareDashedMousePointer size={18} />, "Redact area")}
            <ToolButton icon={<FileSearch size={18} />} label="Redact text" onClick={() => setSidebar("search")} />
            {t("whiteout", <RectangleHorizontal size={18} />, "Whiteout")}
          </Group>
          <Group>
            <ToolButton icon={<Lock size={18} />} label="Password" title="Encrypt with a password" onClick={() => openDialog("protect")} />
            <ToolButton icon={<ShieldOff size={18} />} label="Clean" title="Remove metadata on export" onClick={() => openDialog("protect")} />
          </Group>
          <Group>
            <ToolButton
              icon={<Layers size={18} />}
              label="Flatten all"
              title="Burn annotations and form fields into the page"
              onClick={pagesAction(() => run(() => api.flatten(doc.id, true, true), "Flattened"))}
            />
          </Group>
        </div>
      );
    case "tools":
      return (
        <div className="ribbon" role="toolbar" aria-label="Document tools">
          <Group>
            <ToolButton icon={<Droplets size={18} />} label="Watermark" onClick={() => openDialog("watermark")} />
            <ToolButton icon={<Hash size={18} />} label="Page numbers" title="Header, footer & page numbers" onClick={() => openDialog("headerFooter")} />
          </Group>
          <Group>
            <ToolButton icon={<ScanText size={18} />} label="OCR" title="Recognise text in scanned pages" onClick={() => openDialog("ocr")} />
          </Group>
          <Group>
            <ToolButton icon={<Info size={18} />} label="Properties" onClick={() => openDialog("metadata")} />
            {panel("outline", <BookMarked size={18} />, "Bookmarks")}
          </Group>
          <Group>
            <ToolButton icon={<FileImage size={18} />} label="To images" onClick={() => openDialog("export")} />
            <ToolButton icon={<FileOutput size={18} />} label="Compress" onClick={() => openDialog("export")} />
          </Group>
        </div>
      );
  }
}
