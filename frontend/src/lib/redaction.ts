import type { RedactResult } from "../api/types";

function count(n: number, singular: string, plural: string): string | null {
  if (n <= 0) return null;
  return `${n} ${n === 1 ? singular : plural}`;
}

/** What a redaction also took out besides the page content, e.g. " (also removed 2 comments and 1 link)". */
export function removedNote(result: Pick<RedactResult, "annotations" | "fields" | "links"> | undefined): string {
  if (!result) return "";
  const parts = [
    count(result.annotations, "comment", "comments"),
    count(result.fields, "form field", "form fields"),
    count(result.links, "link", "links"),
  ].filter((part): part is string => part !== null);
  if (parts.length === 0) return "";
  const text = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0];
  return ` (also removed ${text})`;
}
