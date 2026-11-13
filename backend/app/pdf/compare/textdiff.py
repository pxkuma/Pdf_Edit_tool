"""Word-level difference between the text of two pages, with the position of every changed word."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal, Sequence

from ..geometry import Rect4
from .words import Word

CONTEXT_WORDS = 4
ChangeType = Literal["insert", "delete", "replace"]


@dataclass(frozen=True)
class TextChange:
    type: ChangeType
    old_text: str
    new_text: str
    rects_a: tuple[Rect4, ...]  # where the old words are on the first page, one rectangle per line
    rects_b: tuple[Rect4, ...]  # where the new words are on the second page
    anchor_a: Rect4 | None  # an insertion: the place on the first page where the text appears
    anchor_b: Rect4 | None  # a deletion: the place on the second page where the text was
    before: str  # the words just before the change
    after: str  # and just after it

    @property
    def words_deleted(self) -> int:
        return len(self.old_text.split())

    @property
    def words_inserted(self) -> int:
        return len(self.new_text.split())


def line_rects(words: Sequence[Word]) -> tuple[Rect4, ...]:
    """One rectangle per line of the words, in reading order."""
    rects: list[Rect4] = []
    last_line: tuple[int, int] | None = None
    for word in words:
        x0, y0, x1, y1 = word.rect
        if word.line == last_line and rects:
            a0, b0, a1, b1 = rects[-1]
            rects[-1] = (min(a0, x0), min(b0, y0), max(a1, x1), max(b1, y1))
        else:
            rects.append(word.rect)
        last_line = word.line
    return tuple(rects)


def gap_marker(words: Sequence[Word], index: int) -> Rect4 | None:
    """A zero-width rectangle between word ``index - 1`` and ``index``: where text was added or removed."""
    if not words:
        return None
    if index > 0:
        x0, y0, x1, y1 = words[min(index, len(words)) - 1].rect
        return (x1, y0, x1, y1)
    x0, y0, _x1, y1 = words[0].rect
    return (x0, y0, x0, y1)


def _join(words: Sequence[Word]) -> str:
    return " ".join(word.text for word in words)


def diff_words(a: Sequence[Word], b: Sequence[Word]) -> list[TextChange]:
    """The insertions, deletions and replacements that turn the words ``a`` into the words ``b``."""
    matcher = SequenceMatcher(None, [w.key for w in a], [w.key for w in b], autojunk=False)
    changes = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            continue
        kind: ChangeType = "delete" if tag == "delete" else "insert" if tag == "insert" else "replace"
        old, new = a[a0:a1], b[b0:b1]
        changes.append(TextChange(
            type=kind,
            old_text=_join(old),
            new_text=_join(new),
            rects_a=line_rects(old),
            rects_b=line_rects(new),
            anchor_a=gap_marker(a, a0) if kind == "insert" else None,
            anchor_b=gap_marker(b, b0) if kind == "delete" else None,
            before=_join(a[max(0, a0 - CONTEXT_WORDS):a0]),
            after=_join(a[a1:a1 + CONTEXT_WORDS]),
        ))
    return changes
