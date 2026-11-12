"""Reading a page for comparison: its words with positions, plus a tiny picture for pages without text.

Rectangles are in *display* space (rotated page, y down), the same space as the page model and the
renderer, so the UI can draw them on a rendered page without converting anything.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import pymupdf as fitz

from ..geometry import Rect4, to_display_rect

THUMB_W = 24
THUMB_H = 32
SPARSE_WORDS = 8  # a page with fewer words is also described by a thumbnail
WORD_FLAGS = fitz.TEXT_MEDIABOX_CLIP  # ligatures are expanded, so "fi" and its ligature compare equal


@dataclass(frozen=True)
class Word:
    text: str  # as written in the document
    key: str  # normalised form that is compared
    rect: Rect4
    line: tuple[int, int]  # (block, line) the word belongs to


@dataclass(frozen=True)
class PageContent:
    size: tuple[float, float]
    words: tuple[Word, ...]
    thumb: bytes | None = None  # THUMB_W x THUMB_H greyscale, only for pages with few words


def normalize_word(text: str, ignore_case: bool) -> str:
    """Compatibility form without invisible characters, so equal-looking words are equal."""
    folded = unicodedata.normalize("NFKC", text)
    cleaned = "".join(ch for ch in folded if unicodedata.category(ch) not in ("Cf", "Cc", "Zs", "Zl", "Zp"))
    return cleaned.casefold() if ignore_case else cleaned


def page_words(page: fitz.Page, ignore_case: bool) -> tuple[Word, ...]:
    words = []
    for x0, y0, x1, y1, text, block, line, _number in page.get_text("words", flags=WORD_FLAGS):
        key = normalize_word(text, ignore_case)
        if key:
            words.append(Word(text.strip(), key, to_display_rect(page, (x0, y0, x1, y1)), (block, line)))
    return tuple(words)


def page_thumb(page: fitz.Page) -> bytes:
    """A 24x32 greyscale picture of the page; enough to tell a blank page from a drawing."""
    rect = page.rect
    matrix = fitz.Matrix(THUMB_W / max(rect.width, 1), THUMB_H / max(rect.height, 1))
    pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY, alpha=False)
    if (pix.width, pix.height) != (THUMB_W, THUMB_H):
        pix = fitz.Pixmap(pix, THUMB_W, THUMB_H)
    return bytes(pix.samples)


def read_page(page: fitz.Page, ignore_case: bool = False) -> PageContent:
    words = page_words(page, ignore_case)
    thumb = page_thumb(page) if len(words) < SPARSE_WORDS else None
    rect = page.rect
    return PageContent((round(rect.width, 2), round(rect.height, 2)), words, thumb)


def image_rects(page: fitz.Page) -> list[Rect4]:
    """Where pictures are placed on the page (display space)."""
    return [to_display_rect(page, info["bbox"]) for info in page.get_image_info()]
