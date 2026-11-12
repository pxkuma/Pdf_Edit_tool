const KEY = "pdfstudio.commentAuthor";
export const MAX_AUTHOR = 200;

/** The name new comments, replies and statuses are signed with (remembered per browser). */
export function readCommentAuthor(): string {
  try {
    return (localStorage.getItem(KEY) ?? "").slice(0, MAX_AUTHOR);
  } catch {
    return ""; // storage unavailable: comments are simply unsigned
  }
}

export function writeCommentAuthor(name: string): void {
  try {
    localStorage.setItem(KEY, name.slice(0, MAX_AUTHOR));
  } catch {
    /* the name just isn't remembered */
  }
}
