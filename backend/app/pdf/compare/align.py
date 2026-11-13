"""Matching the pages of two documents, so an inserted or removed page does not shift every later pair.

Pages that are identical are anchored first (a diff over page fingerprints). The stretches between
anchors are aligned by page similarity: a monotone matching that maximises the total similarity, so
only pages that really resemble each other are paired. What stays unmatched is inserted or removed.
A stretch with as many unmatched pages on both sides is read as pages that were rewritten and
paired in order.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

from .words import SPARSE_WORDS, PageContent

MATCH_THRESHOLD = 0.4  # pages less similar than this are not the same page
MAX_DP_CELLS = 40_000  # larger unanchored stretches are paired by position instead of searched
THUMB_SCALE = 0.06  # a mean grey difference of this fraction counts as "nothing in common"


@dataclass(frozen=True)
class PageSignature:
    fingerprint: int
    shingles: frozenset[int]  # hashes of the words and word pairs of the page
    words: int
    thumb: bytes | None


@dataclass(frozen=True)
class PagePair:
    a: int | None  # page index in the first document; None = the page exists only in the second
    b: int | None
    similarity: float


def signature(content: PageContent) -> PageSignature:
    keys = [word.key for word in content.words]
    shingles = {hash(key) for key in keys} | {hash((one, two)) for one, two in zip(keys, keys[1:])}
    return PageSignature(hash((tuple(keys), content.thumb)), frozenset(shingles), len(keys), content.thumb)


def _thumb_similarity(one: bytes, two: bytes) -> float:
    if len(one) != len(two) or not one:
        return 0.0
    mean = sum(abs(x - y) for x, y in zip(one, two)) / (255 * len(one))
    return max(0.0, 1.0 - mean / THUMB_SCALE)


def _text_similarity(one: PageSignature, two: PageSignature) -> float:
    if not one.shingles and not two.shingles:
        return 1.0
    total = len(one.shingles) + len(two.shingles)
    if not total or 2 * min(len(one.shingles), len(two.shingles)) / total < MATCH_THRESHOLD:
        return 0.0  # even a perfect overlap of the smaller page could not reach the threshold
    return 2 * len(one.shingles & two.shingles) / total


def similarity(one: PageSignature, two: PageSignature) -> float:
    """0..1: how much two pages look like the same page. Dice overlap of words and word pairs; pages with
    hardly any text are judged by a thumbnail as well."""
    text = _text_similarity(one, two)
    if one.thumb is not None and two.thumb is not None and one.words < SPARSE_WORDS and two.words < SPARSE_WORDS:
        return 0.5 * text + 0.5 * _thumb_similarity(one.thumb, two.thumb)
    return text


def _anchors(a: Sequence[PageSignature], b: Sequence[PageSignature]) -> list[tuple[int, int]]:
    matcher = SequenceMatcher(None, [s.fingerprint for s in a], [s.fingerprint for s in b], autojunk=False)
    return [(block.a + k, block.b + k) for block in matcher.get_matching_blocks() for k in range(block.size)]


def _search_gap(a: Sequence[PageSignature], b: Sequence[PageSignature], a_range: range, b_range: range) -> list[tuple[int, int]]:
    """Best monotone matching of the pages in the two ranges (pages below the threshold never match)."""
    n, m = len(a_range), len(b_range)
    if not n or not m:
        return []
    if n * m > MAX_DP_CELLS:  # too many to search: pair by position and keep the pairs that resemble each other
        return [(i, j) for i, j in zip(a_range, b_range) if similarity(a[i], b[j]) >= MATCH_THRESHOLD]
    sims = [[similarity(a[i], b[j]) for j in b_range] for i in a_range]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            score = max(best[i - 1][j], best[i][j - 1])
            if sims[i - 1][j - 1] >= MATCH_THRESHOLD:
                score = max(score, best[i - 1][j - 1] + sims[i - 1][j - 1])
            best[i][j] = score
    matches, i, j = [], n, m
    while i and j:
        similar = sims[i - 1][j - 1] >= MATCH_THRESHOLD
        if similar and best[i][j] == best[i - 1][j - 1] + sims[i - 1][j - 1]:
            matches.append((a_range[i - 1], b_range[j - 1]))
            i, j = i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return matches[::-1]


def _matches(a: Sequence[PageSignature], b: Sequence[PageSignature]) -> list[tuple[int, int]]:
    anchors = _anchors(a, b)
    found: list[tuple[int, int]] = []
    last_a = last_b = -1
    for anchor_a, anchor_b in [*anchors, (len(a), len(b))]:
        found.extend(_search_gap(a, b, range(last_a + 1, anchor_a), range(last_b + 1, anchor_b)))
        if anchor_a < len(a):
            found.append((anchor_a, anchor_b))
        last_a, last_b = anchor_a, anchor_b
    return found


def align_pages(a: Sequence[PageSignature], b: Sequence[PageSignature]) -> list[PagePair]:
    """Pair up the pages of two documents in reading order."""
    pairs: list[PagePair] = []
    last_a = last_b = -1
    for index_a, index_b in [*_matches(a, b), (len(a), len(b))]:
        removed = list(range(last_a + 1, index_a))
        added = list(range(last_b + 1, index_b))
        if removed and len(removed) == len(added):  # rewritten pages: same place, different content
            pairs.extend(PagePair(i, j, round(similarity(a[i], b[j]), 4)) for i, j in zip(removed, added))
        else:
            pairs.extend(PagePair(i, None, 0.0) for i in removed)
            pairs.extend(PagePair(None, j, 0.0) for j in added)
        if index_a < len(a):
            pairs.append(PagePair(index_a, index_b, round(similarity(a[index_a], b[index_b]), 4)))
        last_a, last_b = index_a, index_b
    return pairs
