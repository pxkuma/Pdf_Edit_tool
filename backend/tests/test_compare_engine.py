"""The comparison engine: page alignment, word-level text changes and visual regions."""

from __future__ import annotations

import pytest
from comparekit import change_summary, make_pdf, open_pdf, paragraph

from app.pdf.compare import MAX_VISUAL_PAIRS, CompareError, CompareOptions, compare_documents
from app.pdf.compare.align import PagePair, align_pages, signature
from app.pdf.compare.words import read_page


def compare(first: bytes, second: bytes, **options) -> dict:
    doc_a, doc_b = open_pdf(first), open_pdf(second)
    return compare_documents(lambda: doc_a, lambda: doc_b, CompareOptions(**options))


def statuses(report: dict) -> list[tuple[str, int | None, int | None]]:
    return [(p["status"], p["pageA"], p["pageB"]) for p in report["pairs"]]


PAGES = [paragraph("alpha"), paragraph("bravo"), paragraph("charlie")]


class TestIdenticalDocuments:
    @pytest.mark.parametrize("mode", ["text", "visual", "both"])
    def test_the_same_document_has_no_changes(self, mode):
        data = make_pdf(PAGES)
        report = compare(data, data, mode=mode)
        assert report["totals"]["changes"] == 0
        assert report["totals"]["pagesWithChanges"] == 0
        assert statuses(report) == [("matched", 0, 0), ("matched", 1, 1), ("matched", 2, 2)]
        assert all(pair["changes"] == [] for pair in report["pairs"])

    def test_a_copy_written_separately_is_still_identical(self):
        report = compare(make_pdf(PAGES), make_pdf(PAGES), mode="both")
        assert report["totals"]["changes"] == 0

    def test_page_sizes_and_word_counts_are_reported(self):
        report = compare(make_pdf(PAGES), make_pdf(PAGES), mode="text")
        pair = report["pairs"][0]
        assert pair["sizeA"] == pair["sizeB"] == [595.0, 842.0]
        assert pair["text"]["wordsA"] == pair["text"]["wordsB"] > 0


class TestTextChanges:
    def test_an_edited_word_is_a_replacement_with_the_right_words(self):
        edited = [list(page) for page in PAGES]
        edited[1][1] = edited[1][1].replace("wording", "phrasing")
        report = compare(make_pdf(PAGES), make_pdf(edited), mode="text")
        assert [p["status"] for p in report["pairs"]] == ["matched", "changed", "matched"]
        assert change_summary(report["pairs"][1]) == [("replace", "wording", "phrasing")]
        assert report["totals"]["textChanges"] == 1
        assert report["totals"]["wordsDeleted"] == report["totals"]["wordsInserted"] == 1

    def test_inserted_and_deleted_words(self):
        edited = [list(page) for page in PAGES]
        edited[0][0] = edited[0][0].replace("alpha line 1", "alpha extra words line 1")
        edited[2][2] = edited[2][2].replace(" wording", "")
        report = compare(make_pdf(PAGES), make_pdf(edited), mode="text")
        assert change_summary(report["pairs"][0]) == [("insert", "", "extra words")]
        assert change_summary(report["pairs"][2]) == [("delete", "wording", "")]
        assert report["totals"]["wordsInserted"] == 2
        assert report["totals"]["wordsDeleted"] == 1

    def test_changes_carry_rectangles_on_the_side_where_the_words_are(self):
        edited = [list(page) for page in PAGES]
        edited[0][1] = edited[0][1].replace("unique", "special")
        change = compare(make_pdf(PAGES), make_pdf(edited), mode="text")["pairs"][0]["changes"][0]
        assert len(change["rectsA"]) == len(change["rectsB"]) == 1
        x0, y0, x1, y1 = change["rectsB"][0]
        assert 72 <= x0 < x1 < 595 and 100 < y0 < y1 < 842
        assert change["oldText"] == "unique" and change["newText"] == "special"

    def test_an_insertion_has_a_place_on_the_page_it_is_missing_from(self):
        edited = [list(page) for page in PAGES]
        edited[0][0] = edited[0][0].replace("carries", "carries some")
        change = compare(make_pdf(PAGES), make_pdf(edited), mode="text")["pairs"][0]["changes"][0]
        assert change["rectsA"] == [] and len(change["rectsB"]) == 1
        assert change["anchorA"] is not None and change["anchorA"][0] == change["anchorA"][2]

    def test_case_differences_count_unless_ignored(self):
        edited = [list(page) for page in PAGES]
        edited[0][0] = edited[0][0].replace("carries", "CARRIES")
        assert compare(make_pdf(PAGES), make_pdf(edited), mode="text")["totals"]["textChanges"] == 1
        assert compare(make_pdf(PAGES), make_pdf(edited), mode="text", ignore_case=True)["totals"]["textChanges"] == 0

    def test_changes_are_numbered_in_reading_order(self):
        edited = [list(page) for page in PAGES]
        edited[0][2] = edited[0][2].replace("unique", "own")
        edited[2][0] = edited[2][0].replace("unique", "own")
        report = compare(make_pdf(PAGES), make_pdf(edited), mode="text")
        changes = [c for p in report["pairs"] for c in p["changes"]]
        assert [c["id"] for c in changes] == ["c0", "c1"]
        assert [c["pair"] for c in changes] == [0, 2]


class TestPageAlignment:
    def test_an_inserted_page_does_not_shift_the_pairs(self):
        revised = [PAGES[0], paragraph("delta"), PAGES[1], PAGES[2]]
        report = compare(make_pdf(PAGES), make_pdf(revised), mode="text")
        assert statuses(report) == [("matched", 0, 0), ("inserted", None, 1), ("matched", 1, 2), ("matched", 2, 3)]
        inserted = report["pairs"][1]["changes"][0]
        assert (inserted["kind"], inserted["type"]) == ("page", "insert")
        assert inserted["newText"].startswith("delta line 1")
        assert inserted["rectsB"] == [[0.0, 0.0, 595.0, 842.0]] and inserted["rectsA"] == []

    def test_a_removed_page(self):
        revised = [PAGES[0], PAGES[2]]
        report = compare(make_pdf(PAGES), make_pdf(revised), mode="text")
        assert statuses(report) == [("matched", 0, 0), ("removed", 1, None), ("matched", 2, 1)]
        assert report["pairs"][1]["changes"][0]["type"] == "delete"

    def test_pages_inserted_at_the_start_and_end(self):
        revised = [paragraph("first"), *PAGES, paragraph("last")]
        report = compare(make_pdf(PAGES), make_pdf(revised), mode="text")
        assert [s[0] for s in statuses(report)] == ["inserted", "matched", "matched", "matched", "inserted"]
        assert report["totals"]["inserted"] == 2 and report["totals"]["pagesWithChanges"] == 2

    def test_an_edited_page_is_still_paired_with_its_original(self):
        edited = [list(page) for page in PAGES]
        edited[1] = [edited[1][0], "totally rewritten second line", edited[1][2]]
        revised = [paragraph("delta"), *edited]
        report = compare(make_pdf(PAGES), make_pdf(revised), mode="text")
        assert statuses(report) == [("inserted", None, 0), ("matched", 0, 1), ("changed", 1, 2), ("matched", 2, 3)]

    def test_pages_of_one_template_are_matched_by_content_not_position(self):
        def invoice(number: int) -> list[str]:
            return ["Invoice", f"Number {number}", "Customer account holder", f"Total due {number * 100}", "Thank you for your business"]

        first = [invoice(n) for n in range(1, 6)]
        second = [invoice(0), *first]
        report = compare(make_pdf(first), make_pdf(second), mode="text")
        assert statuses(report)[0] == ("inserted", None, 0)
        assert all(status == "matched" for status, _a, _b in statuses(report)[1:])

    def test_rewritten_pages_in_the_same_place_are_paired(self):
        report = compare(make_pdf([PAGES[0], PAGES[1]]), make_pdf([PAGES[0], paragraph("zulu", 4)]), mode="text")
        assert statuses(report) == [("matched", 0, 0), ("changed", 1, 1)]

    def test_alignment_of_signatures_directly(self):
        pages = [open_pdf(make_pdf([paragraph(t)]))[0] for t in ("one", "two", "three")]
        sigs = [signature(read_page(page)) for page in pages]
        assert align_pages(sigs, sigs) == [PagePair(0, 0, 1.0), PagePair(1, 1, 1.0), PagePair(2, 2, 1.0)]
        assert align_pages(sigs[:1], []) == [PagePair(0, None, 0.0)]
        assert align_pages([], sigs[:1]) == [PagePair(None, 0, 0.0)]

    def test_pages_without_text_are_aligned_by_their_picture(self):
        def drawn(colors: list[tuple]) -> bytes:
            boxes = {n: [((50, 50, 400, 300), color)] for n, color in enumerate(colors)}
            return make_pdf([[] for _ in colors], boxes=boxes)

        red, green, blue = (1, 0, 0), (0, 0.6, 0), (0, 0, 1)
        report = compare(drawn([red, blue]), drawn([red, green, blue]), mode="text")
        assert statuses(report) == [("matched", 0, 0), ("inserted", None, 1), ("matched", 1, 2)]


class TestVisualChanges:
    def test_a_new_rectangle_is_found_with_its_position(self):
        first = make_pdf(PAGES)
        second = make_pdf(PAGES, boxes={1: [((300, 400, 450, 500), (1, 0, 0))]})
        report = compare(first, second, mode="visual")
        assert [p["status"] for p in report["pairs"]] == ["matched", "changed", "matched"]
        (change,) = report["pairs"][1]["changes"]
        assert (change["kind"], change["type"]) == ("visual", "region")
        x0, y0, x1, y1 = change["rectsB"][0]
        assert 295 <= x0 <= 300 and 395 <= y0 <= 400 and 450 <= x1 <= 455 and 500 <= y1 <= 505
        assert change["rectsA"] == change["rectsB"] and change["pixels"] > 1000

    def test_separate_changes_are_separate_regions(self):
        second = make_pdf(PAGES, boxes={0: [((300, 400, 360, 440), (1, 0, 0)), ((100, 600, 160, 640), (0, 0, 1))]})
        report = compare(make_pdf(PAGES), second, mode="visual")
        assert report["pairs"][0]["visual"]["regions"] == 2

    def test_a_colour_change_is_found(self):
        first = make_pdf(PAGES, boxes={0: [((300, 400, 450, 500), (1, 0, 0))]})
        second = make_pdf(PAGES, boxes={0: [((300, 400, 450, 500), (0, 0, 1))]})
        assert compare(first, second, mode="visual")["totals"]["visualChanges"] == 1

    def test_sensitivity_ignores_small_colour_differences(self):
        first = make_pdf(PAGES, boxes={0: [((300, 400, 450, 500), (0.5, 0.5, 0.5))]})
        second = make_pdf(PAGES, boxes={0: [((300, 400, 450, 500), (0.55, 0.5, 0.5))]})  # 13 of 255 apart
        assert compare(first, second, mode="visual", sensitivity="medium")["totals"]["changes"] == 0
        assert compare(first, second, mode="visual", sensitivity="high")["totals"]["changes"] == 1

    def test_an_edited_word_is_one_text_change_not_also_a_visual_one(self):
        edited = [list(page) for page in PAGES]
        edited[0][1] = edited[0][1].replace("unique", "special")
        report = compare(make_pdf(PAGES), make_pdf(edited), mode="both")
        pair = report["pairs"][0]
        assert [c["kind"] for c in pair["changes"]] == ["text"]
        assert pair["visual"]["explainedByText"] >= 1 and pair["visual"]["regions"] == 0

    def test_visual_mode_alone_reports_the_edited_word_as_a_region(self):
        edited = [list(page) for page in PAGES]
        edited[0][1] = edited[0][1].replace("unique", "special")
        report = compare(make_pdf(PAGES), make_pdf(edited), mode="visual")
        assert [c["kind"] for c in report["pairs"][0]["changes"]] == ["visual"]
        assert report["pairs"][0]["text"] is None

    def test_a_picture_next_to_a_text_edit_is_still_reported(self):
        edited = [list(page) for page in PAGES]
        edited[0][0] = edited[0][0].replace("alpha", "ALPHA", 1)
        second = make_pdf(edited, boxes={0: [((300, 400, 450, 500), (1, 0, 0))]})
        kinds = sorted(c["kind"] for c in compare(make_pdf(PAGES), second, mode="both")["pairs"][0]["changes"])
        assert kinds == ["text", "visual"]

    def test_different_page_sizes_are_a_change(self):
        report = compare(make_pdf([PAGES[0]]), make_pdf([PAGES[0]], size=(612, 792)), mode="text")
        pair = report["pairs"][0]
        assert pair["status"] == "changed" and pair["sizeChanged"]
        assert (pair["changes"][0]["kind"], pair["changes"][0]["type"]) == ("page", "resize")

    def test_resolution_is_capped_for_huge_pages(self):
        from app.pdf.compare.visual import MAX_COMPARE_PIXELS, comparison_dpi

        assert comparison_dpi([(595, 842)], 72) == 72
        assert comparison_dpi([(595, 842)], 600) <= 150
        dpi = comparison_dpi([(14400, 14400)], 150)
        assert (14400 * dpi / 72) ** 2 <= MAX_COMPARE_PIXELS * 1.05
        assert dpi >= 6

    def test_a_page_that_differs_everywhere_is_one_region(self, monkeypatch):
        from app.pdf.compare import visual

        monkeypatch.setattr(visual, "MAX_PIXEL_SCANS", 20)
        first = make_pdf([paragraph("alpha", 20)])
        second = make_pdf([paragraph("omega", 20)])
        (change,) = compare(first, second, mode="visual")["pairs"][0]["changes"]
        assert change["rectsA"] == [[0.0, 0.0, 595.0, 842.0]]

    def test_too_many_pages_for_a_visual_comparison_is_refused(self):
        pages = MAX_VISUAL_PAIRS + 1
        data = make_pdf([[f"page {n}"] for n in range(pages)])
        with pytest.raises(CompareError, match="at most"):
            compare(data, data, mode="visual")
        assert compare(data, data, mode="text")["totals"]["changes"] == 0


def test_the_documents_are_not_modified():
    data_a, data_b = make_pdf(PAGES), make_pdf([PAGES[0], paragraph("delta")])
    doc_a, doc_b = open_pdf(data_a), open_pdf(data_b)
    compare_documents(lambda: doc_a, lambda: doc_b, CompareOptions(mode="both"))
    assert not doc_a.is_dirty and not doc_b.is_dirty
    assert doc_a.xref_length() == open_pdf(data_a).xref_length() and doc_a.page_count == 3


def test_progress_is_reported_for_every_page_and_pair():
    class Recorder:
        total = 0
        steps: list[str] = []

        def advance(self, message: str = "") -> None:
            self.steps.append(message)

    progress = Recorder()
    doc_a, doc_b = open_pdf(make_pdf(PAGES)), open_pdf(make_pdf(PAGES[:2]))
    compare_documents(lambda: doc_a, lambda: doc_b, CompareOptions(mode="text"), progress=progress)
    assert progress.total == len(progress.steps) == 3 + 2 + 3
