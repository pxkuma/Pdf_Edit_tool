"""Search and replace: whole-word matching and reporting characters no font could draw."""

from __future__ import annotations

import pytest

from app.pdf import doctools
from app.pdf.doctools import ToolError
from conftest import make_sample_pdf


def open_doc(client, payload: bytes, name: str = "t.pdf") -> dict:
    response = client.post("/api/documents", files={"file": (name, payload, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ------------------------------------------------------------------ D11: whole-word search
@pytest.mark.parametrize("query, text, expected", [
    ("C++", "I like C++ and C+++ too", 2),  # only the ends that are word characters need a boundary
    ("$5", "Pay $5 or $50", 1),
    ("$5", "Pay x$5 or 5", 1),
    ("(draft)", "A (draft) copy", 1),
    ("cat", "cat concat cat.", 2),
])
def test_whole_word_matching_works_for_queries_with_punctuation(query, text, expected):
    pattern = doctools.search_pattern(query, match_case=True, whole_word=True)
    assert len(pattern.findall(text)) == expected


def test_substring_matching_is_unchanged():
    assert len(doctools.search_pattern("cat", match_case=False, whole_word=False).findall("Cat concat")) == 2


def test_empty_replace_query_is_rejected():
    with pytest.raises(ToolError):
        doctools.search_pattern("", match_case=True, whole_word=False)


def test_replace_reports_characters_no_font_could_draw(client):
    created = open_doc(client, make_sample_pdf())
    response = client.post(f"/api/documents/{created['id']}/text/replace",
                           json={"query": "Second", "replacement": " page"})
    assert response.status_code == 200, response.text
    result = response.json()["data"]["result"]
    assert result["replaced"] == 1 and "" in result["missing_chars"]
