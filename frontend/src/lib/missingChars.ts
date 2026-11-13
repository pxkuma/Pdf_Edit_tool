/** The warning shown when text was written without characters that no installed font can draw. */
export function missingCharsWarning(chars: readonly string[] | undefined): string | null {
  if (!chars?.length) return null;
  return `No installed font contains: ${chars.join(" ")} — those characters were skipped.`;
}
