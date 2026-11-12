import {
  Circle,
  Highlighter,
  Minus,
  PenLine,
  Spline,
  Square,
  StickyNote,
  Strikethrough,
  Stamp,
  Type,
  Underline,
  Waves,
  type LucideIcon,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  Text: StickyNote,
  Highlight: Highlighter,
  Underline,
  StrikeOut: Strikethrough,
  Squiggly: Waves,
  FreeText: Type,
  Ink: PenLine,
  Line: Minus,
  Square,
  Circle,
  Polygon: Spline,
  PolyLine: Spline,
  Stamp,
};

export function CommentTypeIcon({ type, size = 13 }: { type: string; size?: number }) {
  const Icon = ICONS[type] ?? StickyNote;
  return <Icon size={size} aria-hidden />;
}
