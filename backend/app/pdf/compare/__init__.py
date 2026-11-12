"""Compare two PDF documents: page alignment, word-level text differences and visual differences."""

from .engine import MAX_VISUAL_PAIRS, CompareError, CompareOptions, compare_documents

__all__ = ["MAX_VISUAL_PAIRS", "CompareError", "CompareOptions", "compare_documents"]
