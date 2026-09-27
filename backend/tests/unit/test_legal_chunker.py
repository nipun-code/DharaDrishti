"""Chunker tests. All texts are synthetic placeholders that imitate bare-act layout only."""

import itertools

import pytest

from app.services.ingestion.legal_chunker import chunk_act
from app.services.ingestion.pdf_parser import clean_pages
from app.services.ingestion.types import ChunkDraft, PageText
from tests.fixtures.fake_act import FAKE_ACT_PAGES


def words(text: str) -> int:
    """Whitespace token counter: deterministic and easy to reason about in tests."""
    return len(text.split())


def chunk(pages: list[PageText], **kwargs: int) -> list[ChunkDraft]:
    return chunk_act(pages, "TEST", words, **kwargs)


def one_page(text: str, number: int = 1) -> list[PageText]:
    return [PageText(number, text)]


@pytest.fixture(scope="module")
def fake_act_chunks() -> list[ChunkDraft]:
    return chunk(clean_pages(FAKE_ACT_PAGES))


def by_section(chunks: list[ChunkDraft], number: str) -> ChunkDraft:
    [found] = [c for c in chunks if c.section_number == number]
    return found


# ---------------------------------------------------------------- structure detection
def test_detects_every_section_once_in_order(fake_act_chunks: list[ChunkDraft]) -> None:
    assert [c.section_number for c in fake_act_chunks] == ["1", "2", "3", "4A", "5", "6"]


def test_table_of_contents_and_preamble_are_not_chunked(
    fake_act_chunks: list[ChunkDraft],
) -> None:
    all_text = " ".join(c.text for c in fake_act_chunks)

    assert "ARRANGEMENT" not in all_text
    assert "An Act to illustrate" not in all_text


def test_chapter_title_from_next_line_is_title_cased(fake_act_chunks: list[ChunkDraft]) -> None:
    alpha = by_section(fake_act_chunks, "3")

    assert alpha.chapter_number == "II"
    assert alpha.chapter_title == "Of Placeholder Matters"


def test_chapter_title_on_same_line_after_dash(fake_act_chunks: list[ChunkDraft]) -> None:
    gamma = by_section(fake_act_chunks, "5")

    assert gamma.chapter_number == "III"
    assert gamma.chapter_title == "Of More Placeholders"


def test_section_title_and_body_split_at_em_dash(fake_act_chunks: list[ChunkDraft]) -> None:
    first = by_section(fake_act_chunks, "1")

    assert first.section_title == "Placeholder short title"
    assert first.text.startswith("(1) This Placeholder may be called")
    assert "(2) It applies to nothing" in first.text


@pytest.mark.parametrize(
    ("section", "expected_body"),
    [
        ("5", "Text with an en dash separator."),
        ("6", "Text with an ASCII double hyphen separator."),
    ],
)
def test_dash_variants(fake_act_chunks: list[ChunkDraft], section: str, expected_body: str) -> None:
    assert by_section(fake_act_chunks, section).text == expected_body


def test_wrapped_section_title_is_joined(fake_act_chunks: list[ChunkDraft]) -> None:
    beta = by_section(fake_act_chunks, "4A")

    assert (
        beta.section_title == "Placeholder rule beta with a heading that wraps onto a second line"
    )
    assert beta.text == "Whoever does a second placeholder act shall be liable."


def test_alphanumeric_section_numbers_supported(fake_act_chunks: list[ChunkDraft]) -> None:
    assert "4A" in {c.section_number for c in fake_act_chunks}


def test_schedule_ends_the_last_section(fake_act_chunks: list[ChunkDraft]) -> None:
    delta = by_section(fake_act_chunks, "6")

    assert "schedule" not in delta.text.lower()
    assert "7" not in {c.section_number for c in fake_act_chunks}


def test_explanation_and_illustration_stay_with_section(
    fake_act_chunks: list[ChunkDraft],
) -> None:
    alpha = by_section(fake_act_chunks, "3")

    assert "Explanation.—A placeholder act" in alpha.text
    assert "A does a placeholder act." in alpha.text


def test_words_hyphenated_across_lines_are_rejoined(fake_act_chunks: list[ChunkDraft]) -> None:
    assert "liable to a placeholder consequence." in by_section(fake_act_chunks, "3").text


def test_clauses_keep_their_own_lines(fake_act_chunks: list[ChunkDraft]) -> None:
    definitions = by_section(fake_act_chunks, "2")

    assert definitions.text.splitlines() == [
        "In this Placeholder, unless the context otherwise requires,—",
        '(a) "widget" means a placeholder object;',
        '(b) "gadget" means another placeholder object.',
    ]


def test_running_headers_and_page_numbers_do_not_leak(fake_act_chunks: list[ChunkDraft]) -> None:
    for c in fake_act_chunks:
        assert "PLACEHOLDER SANHITA, 0000" not in c.text
        assert not any(line.strip().isdigit() for line in c.text.splitlines())


# ---------------------------------------------------------------- pages & metadata
def test_page_ranges(fake_act_chunks: list[ChunkDraft]) -> None:
    assert (
        by_section(fake_act_chunks, "1").page_start,
        by_section(fake_act_chunks, "1").page_end,
    ) == (2, 2)
    assert by_section(fake_act_chunks, "4A").page_start == 4


def test_section_spanning_pages_has_page_range() -> None:
    pages = [
        PageText(7, "CHAPTER IV\nOF SPANNING\n9. Spanning rule.—Starts on one page"),
        PageText(8, "and continues on the next page."),
    ]

    [c] = chunk(pages)

    assert (c.page_start, c.page_end) == (7, 8)
    assert c.text == "Starts on one page and continues on the next page."


def test_short_section_is_single_chunk_without_subsection(
    fake_act_chunks: list[ChunkDraft],
) -> None:
    assert all(c.subsection is None for c in fake_act_chunks)


def test_token_count_uses_supplied_counter(fake_act_chunks: list[ChunkDraft]) -> None:
    for c in fake_act_chunks:
        assert c.token_count == words(c.text)


def test_context_header_with_chapter(fake_act_chunks: list[ChunkDraft]) -> None:
    alpha = by_section(fake_act_chunks, "3")

    assert alpha.context_header == (
        "[TEST | Chapter II: Of Placeholder Matters | Section 3: Placeholder rule alpha]"
    )
    assert alpha.embedding_text == f"{alpha.context_header}\n{alpha.text}"


def test_context_header_without_chapter() -> None:
    [c] = chunk(one_page("1. Lonely rule.—Body text."))

    assert c.chapter_number is None
    assert c.context_header == "[TEST | Section 1: Lonely rule]"


def test_mixed_case_titles_are_preserved() -> None:
    [c] = chunk(one_page("CHAPTER V\nOF THINGS\n10. Rule about the XYZ register.—Body."))

    assert c.section_title == "Rule about the XYZ register"


def test_all_caps_section_title_is_title_cased() -> None:
    [c] = chunk(one_page("11. SHOUTED HEADING.—Body."))

    assert c.section_title == "Shouted Heading"


# ---------------------------------------------------------------- edge cases
def test_empty_input() -> None:
    assert chunk([]) == []


def test_text_without_sections_yields_nothing() -> None:
    assert chunk(one_page("Just a preamble.\nNo numbered headings here.")) == []


def test_section_with_empty_body_is_skipped() -> None:
    chunks = chunk(one_page("12. Empty rule.—\n13. Next rule.—Has a body."))

    assert [c.section_number for c in chunks] == ["13"]


def test_toc_entry_is_not_joined_with_following_heading() -> None:
    chunks = chunk(one_page("14. Listed only.\n15. Real rule.—Real body."))

    assert [(c.section_number, c.text) for c in chunks] == [("15", "Real body.")]


def test_lowercase_chapter_reference_in_body_is_not_a_heading() -> None:
    [c] = chunk(one_page("16. Referring rule.—See the rules\nChapter II applies here too."))

    assert c.chapter_number is None
    assert c.text == "See the rules Chapter II applies here too."


def test_act_without_chapters_toc_schedule_entry_does_not_hide_body() -> None:
    pages = one_page(
        "1. Placeholder title.\n2. Placeholder scope.\nTHE SCHEDULE.\n"
        "1. Placeholder title.—Body one.\n2. Placeholder scope.—Body two.\n"
        "THE SCHEDULE\n3. Schedule item.—Not a section."
    )

    chunks = chunk(pages)

    assert [(c.section_number, c.text) for c in chunks] == [("1", "Body one."), ("2", "Body two.")]


def test_chapter_heading_after_schedule_resumes_sections() -> None:
    pages = one_page(
        "THE SCHEDULE\n8. Schedule item.—Ignored.\nCHAPTER X\nOF LATER THINGS\n"
        "9. Later rule.—Counted."
    )

    assert [c.section_number for c in chunk(pages)] == ["9"]


def test_invalid_overlap_rejected() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk(one_page("1. X.—y"), max_tokens=10, overlap_tokens=10)


# ---------------------------------------------------------------- long sections
def long_section() -> list[PageText]:
    """A placeholder section of five sub-sections, 20 words each (100 words + intro)."""
    subsections = [f"({n}) " + " ".join(f"filler{n}w{i}" for i in range(19)) for n in range(1, 6)]
    body = "\n".join(subsections)
    return [
        PageText(1, "CHAPTER IX\nOF LONG PLACEHOLDERS\n20. Long rule.—Intro words here.\n"),
        PageText(2, body),
    ]


def test_long_section_split_at_subsections_with_overlap() -> None:
    pieces = chunk(long_section(), max_tokens=50, overlap_tokens=10)

    assert len(pieces) > 1
    for piece in pieces:
        assert piece.section_number == "20"
        assert piece.section_title == "Long rule"
        assert piece.chapter_title == "Of Long Placeholders"
        assert piece.token_count <= 50
    # Every piece after the first starts with the tail of the previous one.
    for prev, cur in itertools.pairwise(pieces):
        overlap = cur.text.splitlines()[0]
        assert words(overlap) >= 10
        assert prev.text.endswith(overlap)


def test_long_section_pieces_carry_enclosing_subsection() -> None:
    pieces = chunk(long_section(), max_tokens=50, overlap_tokens=10)

    assert pieces[0].subsection is None  # starts with the intro text
    assert [p.subsection for p in pieces[1:]] == sorted(
        {p.subsection for p in pieces[1:]}, key=lambda s: int(s.strip("()"))
    )
    assert all(p.subsection and p.subsection.startswith("(") for p in pieces[1:])


def test_long_section_covers_all_text_without_loss() -> None:
    pieces = chunk(long_section(), max_tokens=50, overlap_tokens=10)
    joined = " ".join(p.text for p in pieces)

    for n in range(1, 6):
        for i in range(19):
            assert f"filler{n}w{i}" in joined


def test_long_section_without_overlap() -> None:
    pieces = chunk(long_section(), max_tokens=50, overlap_tokens=0)

    assert sum(p.token_count for p in pieces) == 3 + 5 * 20  # no duplicated words


def test_single_oversized_subsection_split_by_sentences() -> None:
    sentences = " ".join(f"Sentence {i} has exactly six words." for i in range(12))
    pages = one_page(f"30. Wordy rule.—(1) {sentences}")

    pieces = chunk(pages, max_tokens=30, overlap_tokens=5)

    assert len(pieces) > 1
    assert all(p.token_count <= 30 for p in pieces)
    assert all(p.subsection == "(1)" for p in pieces)
    # Splits happen between sentences, never mid-sentence (apart from the overlap prefix).
    for p in pieces:
        assert p.text.splitlines()[-1].endswith("words.")


def test_single_oversized_sentence_split_by_words() -> None:
    run_on = " ".join(f"w{i}" for i in range(100))
    pieces = chunk(one_page(f"31. Run-on rule.—{run_on}"), max_tokens=25, overlap_tokens=5)

    assert all(p.token_count <= 25 for p in pieces)
    joined = " ".join(p.text for p in pieces)
    assert all(f"w{i}" in joined.split() for i in range(100))


def test_split_pieces_track_their_own_pages() -> None:
    pieces = chunk(long_section(), max_tokens=50, overlap_tokens=10)

    assert pieces[0].page_start == 1
    assert pieces[-1].page_end == 2
