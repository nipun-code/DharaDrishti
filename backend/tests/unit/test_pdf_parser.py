"""PDF extraction and header/footer cleaning, using PDFs generated from placeholder text."""

from pathlib import Path

import pytest

from app.services.ingestion.pdf_parser import clean_pages, extract_pages
from app.services.ingestion.types import IngestionError, PageText

pymupdf = pytest.importorskip("pymupdf")


def make_pdf(path: Path, pages: list[str]) -> Path:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        y = 72
        for line in text.splitlines():
            page.insert_text((72, y), line, fontsize=10)
            y += 14
    doc.save(path)
    doc.close()
    return path


# ---------------------------------------------------------------- extraction
def test_extract_pages_returns_text_per_page(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "fake.pdf", ["1. Placeholder rule.--Body one.", "Second page text."])

    pages = extract_pages(pdf)

    assert [p.number for p in pages] == [1, 2]
    assert "Placeholder rule" in pages[0].text
    assert "Second page text." in pages[1].text


def test_extract_pages_rejects_pdf_without_text(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "blank.pdf", ["", ""])

    with pytest.raises(IngestionError, match="no extractable text"):
        extract_pages(pdf)


def test_extract_pages_rejects_corrupt_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\nthis is not really a pdf")

    with pytest.raises(IngestionError, match="Could not read"):
        extract_pages(bad)


def test_extract_pages_rejects_encrypted_pdf(tmp_path: Path) -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret placeholder")
    path = tmp_path / "locked.pdf"
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    doc.close()

    with pytest.raises(IngestionError, match="password"):
        extract_pages(path)


# ---------------------------------------------------------------- cleaning
def page(number: int, *lines: str) -> PageText:
    return PageText(number, "\n".join(lines))


BODIES = ["Alpha placeholder body.", "Beta text here.", "Gamma words.", "Delta.", "Epsilon end."]


def test_running_header_and_footer_removed() -> None:
    pages = [
        page(n, "THE PLACEHOLDER SANHITA, 0000", body, f"Footer text {n}")
        for n, body in enumerate(BODIES, start=1)
    ]

    cleaned = clean_pages(pages)

    assert [p.text for p in cleaned] == BODIES


def test_repeated_line_at_varying_positions_is_kept() -> None:
    # "Common sentence." is on every page, but its distance from the top/bottom differs, so it
    # is body text, not a running header. "Header" is always first, so it is stripped.
    letters = "abcdefghij"
    pages = []
    for n in range(1, 6):
        before = [f"lead {letters[n]}{letters[i]}" for i in range(n)]
        after = [f"tail {letters[n]}{letters[i]}" for i in range(6 - n)]
        pages.append(page(n, "Header", *before, "Common sentence.", *after))

    cleaned = clean_pages(pages, edge_lines=2)

    assert all("Common sentence." in p.text for p in cleaned)
    assert all("Header" not in p.text for p in cleaned)


def test_page_numbers_removed_from_edges_only() -> None:
    pages = [
        page(1, "12", "Body text", "mentions 12 inline", "- 13 -"),
        page(2, "Page 3 of 90", "Body"),
    ]

    cleaned = clean_pages(pages, edge_lines=1)

    assert cleaned[0].text == "Body text\nmentions 12 inline"
    assert cleaned[1].text == "Body"


def test_line_repeated_on_few_pages_is_kept() -> None:
    pages = [page(1, "Repeated heading", "a"), page(2, "Repeated heading", "b")] + [
        page(n, "Other", str(n) + " body") for n in range(3, 11)
    ]

    cleaned = clean_pages(pages)

    assert cleaned[0].text.startswith("Repeated heading")


def test_repeated_line_in_middle_of_page_is_kept() -> None:
    pages = [page(n, "top", "a", "b", "c", "Whoever", "d", "e", "f", "bottom") for n in range(6)]

    cleaned = clean_pages(pages)

    assert all("Whoever" in p.text for p in cleaned)
    assert all("top" not in p.text for p in cleaned)


def test_page_numbers_inside_running_header_do_not_defeat_detection() -> None:
    pages = [page(n, f"Placeholder Act page {n}", BODIES[n]) for n in range(1, 5)]

    cleaned = clean_pages(pages)

    assert [p.text for p in cleaned] == BODIES[1:5]


def test_blank_lines_dropped_and_page_numbers_preserved() -> None:
    cleaned = clean_pages([PageText(7, "\n\n  Body  \n\n")])

    assert cleaned == [PageText(7, "Body")]


def test_india_code_watermark_removed_anywhere_in_text() -> None:
    text = "Opening line\nplaceholder insultIndiaCodewords here\nIndiaCode\nLast line"

    cleaned = clean_pages([PageText(1, text)])

    assert cleaned[0].text == "Opening line\nplaceholder insult words here\nLast line"
