/**
 * Document-changing requests (edits, undo, redo) must reach the server and update the UI in the order
 * they were asked for. Two quick actions otherwise race: whichever response arrives last wins, which can
 * move the history cursor and the page tokens backwards.
 */
let tail: Promise<unknown> = Promise.resolve();

/** Run `work` after everything requested before it has finished. A failure is passed to its own caller only. */
export function serialized<T>(work: () => Promise<T>): Promise<T> {
  const result = tail.then(work);
  tail = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}
