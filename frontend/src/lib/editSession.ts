/**
 * Inline editors (text runs, paragraphs, new text boxes) register a commit
 * function here. Anything that would discard the editor (switching tools,
 * undo, zooming, downloading) flushes it first so no typing is ever lost.
 */
type Commit = () => Promise<void>;

let current: Commit | null = null;

export function registerCommit(commit: Commit | null): void {
  current = commit;
}

export async function flushEdit(): Promise<void> {
  const commit = current;
  current = null;
  if (commit) await commit();
}

export function hasPendingEdit(): boolean {
  return current !== null;
}
