"""PDF text extraction (PyMuPDF) and removal of running headers, footers and page numbers."""

import math
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from app.services.ingestion.types import IngestionError, PageText

PAGE_NUMBER_RE = re.compile(
    r"^(?:page\s*)?[-–—]?\s*\d{1,4}\s*[-–—]?(?:\s*(?:of|/)\s*\d{1,4})?$", re.IGNORECASE
)

EdgeKey = tuple[str, int, str]  # ("t" | "b", position from top/bottom, normalized text)


def extract_pages(path: Path) -> list[PageText]:
    """Extract text page by page. Raises IngestionError for unreadable or text-less PDFs."""
    import pymupdf  # noqa: PLC0415  # heavy import, only needed in the worker

    try:
        document = pymupdf.open(path)
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise IngestionError("Could not read the PDF file (corrupt or not a PDF).") from exc
    with document:
        if document.needs_pass:
            raise IngestionError("The PDF is password-protected.")
        pages = [
            PageText(number=index + 1, text=str(document[index].get_text("text", sort=True)))
            for index in range(document.page_count)
        ]
    if not any(page.text.strip() for page in pages):
        raise IngestionError(
            "The PDF has no extractable text (scanned PDFs need OCR, which is not supported)."
        )
    return pages


def _normalize(line: str) -> str:
    """Key used to recognise the same header on different pages (page numbers vary)."""
    return re.sub(r"\d+", "#", " ".join(line.lower().split()))


def _edge_keys(lines: Sequence[str], index: int, edge_lines: int) -> list[EdgeKey]:
    """Position-aware keys for a line near the top and/or bottom of its page."""
    keys: list[EdgeKey] = []
    if index < edge_lines:
        keys.append(("t", index, _normalize(lines[index])))
    from_bottom = len(lines) - 1 - index
    if from_bottom < edge_lines:
        keys.append(("b", from_bottom, _normalize(lines[index])))
    return keys


def clean_pages(
    pages: Sequence[PageText],
    *,
    edge_lines: int = 3,
    min_repeat_ratio: float = 0.5,
    min_repeat_pages: int = 3,
) -> list[PageText]:
    """Drop running headers/footers and page numbers.

    A line counts as a running header/footer when it sits at the *same position* among the
    first/last `edge_lines` non-empty lines of a page and (after normalising digits) repeats
    there on at least max(`min_repeat_pages`, `min_repeat_ratio` x pages) pages. Bare page
    numbers ("12", "- 12 -", "Page 3 of 90") are dropped from page edges unconditionally.
    """
    split_pages = [[ln.strip() for ln in p.text.splitlines() if ln.strip()] for p in pages]

    counts: Counter[EdgeKey] = Counter()
    for lines in split_pages:
        counts.update({key for i in range(len(lines)) for key in _edge_keys(lines, i, edge_lines)})
    threshold = max(min_repeat_pages, math.ceil(min_repeat_ratio * len(pages)))
    repeated = {key for key, count in counts.items() if count >= threshold}

    cleaned: list[PageText] = []
    for page, lines in zip(pages, split_pages, strict=True):
        kept = []
        for index, line in enumerate(lines):
            keys = _edge_keys(lines, index, edge_lines)
            if keys and (PAGE_NUMBER_RE.match(line) or any(k in repeated for k in keys)):
                continue
            kept.append(line)
        cleaned.append(PageText(number=page.number, text="\n".join(kept)))
    return cleaned
