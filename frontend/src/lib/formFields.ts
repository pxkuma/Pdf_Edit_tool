/** Pure helpers of form authoring: which tool makes which field, default sizes, option lists, proposals, tab order. */
import type { FieldChoice, FieldProposal, FormField, FormFieldKind, NewFieldRequest, Point, Rect } from "../api/types";

export type NewFieldKind = Exclude<FormFieldKind, "unknown">;

export const FIELD_TOOLS = {
  fieldText: "text",
  fieldCheckbox: "checkbox",
  fieldRadio: "radio",
  fieldCombobox: "combobox",
  fieldListbox: "listbox",
  fieldButton: "button",
  fieldSignature: "signature",
} as const satisfies Record<string, NewFieldKind>;

export type FieldTool = keyof typeof FIELD_TOOLS;

export function isFieldTool(tool: string): tool is FieldTool {
  return Object.prototype.hasOwnProperty.call(FIELD_TOOLS, tool);
}

export const KIND_LABEL: Record<NewFieldKind, string> = {
  text: "Text field",
  checkbox: "Check box",
  radio: "Radio button",
  combobox: "Dropdown",
  listbox: "List box",
  button: "Button",
  signature: "Signature field",
};

/** Size (pt) of a field made with a single click. */
const DEFAULT_SIZE: Record<NewFieldKind, [number, number]> = {
  text: [160, 20],
  checkbox: [14, 14],
  radio: [14, 14],
  combobox: [140, 20],
  listbox: [140, 60],
  button: [100, 26],
  signature: [180, 50],
};

export const MIN_FIELD_SIDE = 6;

/** The rectangle of a new field: the dragged one, or the default size at the clicked point. */
export function newFieldRect(kind: NewFieldKind, dragged: Rect, isClick: boolean, at: Point): Rect {
  if (!isClick) return dragged;
  const [w, h] = DEFAULT_SIZE[kind];
  return [at[0], at[1], at[0] + w, at[1] + h];
}

export function tooSmall(rect: Rect): boolean {
  return rect[2] - rect[0] < MIN_FIELD_SIDE || rect[3] - rect[1] < MIN_FIELD_SIDE;
}

/** One option per line: "label", or "value=label" when the exported value differs from what is shown. */
export function parseChoices(text: string): FieldChoice[] {
  const choices: FieldChoice[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const at = line.indexOf("=");
    if (at > 0 && line.slice(at + 1).trim()) {
      choices.push({ value: line.slice(0, at).trim(), label: line.slice(at + 1).trim() });
    } else {
      choices.push({ value: line, label: line });
    }
  }
  return choices;
}

export function choicesToText(choices: FieldChoice[]): string {
  return choices.map((c) => (c.value === c.label ? c.value : `${c.value}=${c.label}`)).join("\n");
}

/** The first repeated export value, so the form can say so before the server does. */
export function duplicateChoice(choices: FieldChoice[]): string | null {
  const seen = new Set<string>();
  for (const { value } of choices) {
    if (seen.has(value)) return value;
    seen.add(value);
  }
  return null;
}

/** What a list field currently has selected, as an array. */
export function selectedValues(field: FormField): string[] {
  const { value } = field;
  if (Array.isArray(value)) return value;
  return typeof value === "string" && value ? [value] : [];
}

export function fieldTitle(field: FormField): string {
  return field.tooltip || field.label || field.name;
}

// ------------------------------------------------------------------ detected fields
export function proposalRequest(proposal: FieldProposal): NewFieldRequest {
  const props: NewFieldRequest["props"] = { name: proposal.name };
  if (proposal.label && proposal.kind !== "checkbox") props.tooltip = proposal.label;
  if (proposal.multiline) props.multiline = true;
  if (proposal.format) props.format = { kind: "date", decimals: 2, pattern: proposal.format.pattern };
  return { page: proposal.page, kind: proposal.kind, rect: proposal.rect, props };
}

export function acceptedProposals(all: FieldProposal[], rejected: ReadonlySet<string>): FieldProposal[] {
  return all.filter((p) => !rejected.has(p.id));
}

export function toggled(set: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

// ------------------------------------------------------------------ tab order
/** ``ids`` with the entry at ``index`` moved by ``delta`` places (unchanged when that falls off either end). */
export function moveInOrder<T>(ids: readonly T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (index < 0 || index >= ids.length || target < 0 || target >= ids.length) return [...ids];
  const next = [...ids];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item);
  return next;
}
