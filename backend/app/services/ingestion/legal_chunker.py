"""Structure-aware chunker for bare-act text: Act -> Chapter -> Section -> Sub-section.

Detection rules (tuned to the India Code bare-act layout):

* Chapter heading: a line "CHAPTER <ROMAN>" (upper case), with the title either on the same
  line or on the next line, e.g. "CHAPTER XVII" / "OF OFFENCES AGAINST PROPERTY".
* Section heading: "<number>. <Title>.—<body...>", e.g. "318. Cheating.—Whoever ...". The
  ".—" separator (em/en dash or "-"/"--") is required; it is what distinguishes a real heading
  from the "ARRANGEMENT OF SECTIONS" table of contents ("318. Cheating."). Titles that wrap onto
  the next line(s) are joined.
* A "SCHEDULE" heading ends the section body and starts "schedule mode", in which numbered
  entries are not treated as sections (schedules are not chunked). Because the table of
  contents usually lists "THE FIRST SCHEDULE" too, schedule mode ends at the next CHAPTER
  heading or when section numbering restarts at "1" (the start of the real act body).
* Text before the first section (title page, table of contents, preamble) is not chunked.

One chunk per section. A section over `max_tokens` is split at sub-section / clause /
Explanation / Illustration boundaries (falling back to sentences, then words), and each piece
after the first starts with ~`overlap_tokens` of the previous piece. Every piece keeps the
section number and title.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from app.services.ingestion.types import ChunkDraft, PageText

TokenCounter = Callable[[str], int]

_DASH = r"(?:—|–|―|-{1,2})"
CHAPTER_RE = re.compile(
    r"^CHAPTER\s+(?P<num>[IVXLCDM]+[A-Z]?)\b\.?\s*(?:[:.—–-]\s*)?(?P<title>.*)$"
)
SECTION_START_RE = re.compile(r"^(?P<num>\d{1,4}[A-Z]{0,3})\.\s+(?P<after>[A-Z\[(].*)$")
SECTION_TITLE_RE = re.compile(rf"^(?P<title>.+?)[.:]\s*{_DASH}\s*(?P<rest>.*)$")
SCHEDULE_RE = re.compile(r"^(?:THE\s+(?:[A-Z]+\s+)?)?SCHEDULE\b")
UNIT_START_RE = re.compile(
    r"^(?:\((?P<num>\d+[A-Z]?)\)"  # (1) (2A)      sub-section
    r"|\((?P<clause>[a-z]{1,2}|[ivxl]{1,5})\)"  # (a) (iv)   clause
    r"|(?P<kw>Explanation|Illustrations?|Provided|Exception)\b)"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;:])\s+")
_MAX_TITLE_LENGTH = 250
_TITLE_LOOKAHEAD_LINES = 2


@dataclass(frozen=True, slots=True)
class _Line:
    page: int
    text: str


@dataclass(slots=True)
class _Section:
    chapter_number: str | None
    chapter_title: str | None
    number: str
    title: str
    lines: list[_Line] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Unit:
    """A sub-section, clause, Explanation, etc. `subsection` is the enclosing "(n)" if any."""

    subsection: str | None
    text: str
    page_start: int
    page_end: int


# ---------------------------------------------------------------- helpers
def _is_mostly_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) >= 0.8  # noqa: PLR2004


def _nice_title(text: str) -> str:
    """Normalize an ALL-CAPS heading to Title Case; leave mixed-case text alone."""
    text = " ".join(text.split()).strip(" .:—–-")
    if _is_mostly_upper(text):
        return " ".join(word.capitalize() for word in text.split())
    return text


def _join_lines(lines: Iterable[str]) -> str:
    """Join wrapped lines into one paragraph, repairing words hyphenated across lines."""
    out = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if out.endswith("-") and len(out) > 1 and out[-2].isalpha() and line[:1].islower():
            out = out[:-1] + line
        else:
            out = f"{out} {line}" if out else line
    return out


def _to_lines(pages: Sequence[PageText]) -> list[_Line]:
    lines: list[_Line] = []
    for page in pages:
        for raw in page.text.splitlines():
            text = " ".join(raw.split())
            if text:
                lines.append(_Line(page.number, text))
    return lines


def _match_section_heading(lines: Sequence[_Line], i: int) -> tuple[str, str, str, int] | None:
    """If lines[i] starts a section, return (number, title, rest_of_line, lines_consumed)."""
    start = SECTION_START_RE.match(lines[i].text)
    if not start:
        return None
    candidate = start.group("after")
    for extra in range(_TITLE_LOOKAHEAD_LINES + 1):
        titled = SECTION_TITLE_RE.match(candidate)
        if titled and len(titled.group("title")) <= _MAX_TITLE_LENGTH:
            title = _nice_title(titled.group("title"))
            return start.group("num"), title, titled.group("rest"), extra + 1
        nxt = i + extra + 1
        if nxt >= len(lines) or _is_boundary(lines, nxt):
            return None
        candidate = f"{candidate} {lines[nxt].text}"
    return None


def _is_boundary(lines: Sequence[_Line], i: int) -> bool:
    text = lines[i].text
    return bool(CHAPTER_RE.match(text) or SCHEDULE_RE.match(text) or SECTION_START_RE.match(text))


# ---------------------------------------------------------------- parsing
def _parse_sections(lines: Sequence[_Line]) -> list[_Section]:
    sections: list[_Section] = []
    chapter_number: str | None = None
    chapter_title: str | None = None
    current: _Section | None = None
    in_schedule = False
    i = 0
    while i < len(lines):
        text = lines[i].text

        chapter = CHAPTER_RE.match(text)
        if chapter and _is_mostly_upper(text):
            chapter_number = chapter.group("num")
            title = chapter.group("title").strip()
            consumed = 1
            if not title and i + 1 < len(lines):
                nxt = lines[i + 1].text
                if _is_mostly_upper(nxt) and not _is_boundary(lines, i + 1):
                    title, consumed = nxt, 2
            chapter_title = _nice_title(title) or None
            current = None
            in_schedule = False
            i += consumed
            continue

        if SCHEDULE_RE.match(text):
            current = None
            in_schedule = True
            i += 1
            continue

        heading = _match_section_heading(lines, i)
        if heading and in_schedule and heading[0] != "1":
            heading = None
        if heading:
            number, title, rest, consumed = heading
            in_schedule = False
            current = _Section(chapter_number, chapter_title, number, title)
            sections.append(current)
            if rest.strip():
                current.lines.append(_Line(lines[i].page, rest))
            # Pages of wrapped title lines don't matter: the body starts after them.
            i += consumed
            continue

        if current is not None:
            current.lines.append(lines[i])
        i += 1
    return sections


def _units(section: _Section) -> list[_Unit]:
    """Group a section's lines into sub-section / clause units."""
    groups: list[tuple[str | None, list[_Line]]] = []
    enclosing: str | None = None
    for line in section.lines:
        marker = UNIT_START_RE.match(line.text)
        if marker or not groups:
            if marker and marker.group("num"):
                enclosing = f"({marker.group('num')})"
            groups.append((enclosing, [line]))
        else:
            groups[-1][1].append(line)
    return [
        _Unit(
            subsection=label,
            text=_join_lines(line.text for line in group),
            page_start=group[0].page,
            page_end=group[-1].page,
        )
        for label, group in groups
    ]


# ---------------------------------------------------------------- splitting
def _split_words(text: str, budget: int, count: TokenCounter) -> list[str]:
    pieces: list[str] = []
    words: list[str] = []
    used = 0
    for word in text.split():
        cost = count(word)
        if words and used + cost > budget:
            pieces.append(" ".join(words))
            words, used = [], 0
        words.append(word)
        used += cost
    if words:
        pieces.append(" ".join(words))
    return pieces


def _split_oversized(unit: _Unit, budget: int, count: TokenCounter) -> list[_Unit]:
    """Break a unit that alone exceeds the budget: by sentences, then by words."""
    parts: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(unit.text):
        if count(sentence) > budget:
            parts.extend(_split_words(sentence, budget, count))
        else:
            parts.append(sentence)
    packed: list[str] = []
    current: list[str] = []
    used = 0
    for part in parts:
        cost = count(part)
        if current and used + cost > budget:
            packed.append(" ".join(current))
            current, used = [], 0
        current.append(part)
        used += cost
    if current:
        packed.append(" ".join(current))
    return [_Unit(unit.subsection, text, unit.page_start, unit.page_end) for text in packed]


def _overlap_tail(text: str, overlap_tokens: int, count: TokenCounter) -> str:
    words = text.split()
    tail: list[str] = []
    used = 0
    for word in reversed(words):
        if used >= overlap_tokens:
            break
        tail.append(word)
        used += count(word)
    return " ".join(reversed(tail))


def _pack(units: Sequence[_Unit], budget: int, count: TokenCounter) -> list[list[_Unit]]:
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    used = 0
    for unit in units:
        cost = count(unit.text)
        if current and used + cost > budget:
            groups.append(current)
            current, used = [], 0
        current.append(unit)
        used += cost
    if current:
        groups.append(current)
    return groups


# ---------------------------------------------------------------- public API
def chunk_act(
    pages: Sequence[PageText],
    act_code: str,
    count_tokens: TokenCounter,
    *,
    max_tokens: int = 600,
    overlap_tokens: int = 80,
) -> list[ChunkDraft]:
    """Turn cleaned page texts of one act into section-level chunks."""
    if not 0 <= overlap_tokens < max_tokens:
        raise ValueError("overlap_tokens must be >= 0 and < max_tokens")

    drafts: list[ChunkDraft] = []
    for section in _parse_sections(_to_lines(pages)):
        units = [u for u in _units(section) if u.text]
        if not units:
            continue

        def draft(
            text: str,
            subsection: str | None,
            page_start: int,
            page_end: int,
            section: _Section = section,
        ) -> ChunkDraft:
            return ChunkDraft(
                act_code=act_code,
                chapter_number=section.chapter_number,
                chapter_title=section.chapter_title,
                section_number=section.number,
                section_title=section.title,
                subsection=subsection,
                text=text,
                page_start=page_start,
                page_end=page_end,
                token_count=count_tokens(text),
            )

        full_text = "\n".join(u.text for u in units)
        if count_tokens(full_text) <= max_tokens:
            drafts.append(draft(full_text, None, units[0].page_start, units[-1].page_end))
            continue

        budget = max_tokens - overlap_tokens
        sized: list[_Unit] = []
        for unit in units:
            if count_tokens(unit.text) > budget:
                sized.extend(_split_oversized(unit, budget, count_tokens))
            else:
                sized.append(unit)

        previous_text: str | None = None
        for group in _pack(sized, budget, count_tokens):
            body = "\n".join(u.text for u in group)
            if previous_text is not None and overlap_tokens:
                body = f"{_overlap_tail(previous_text, overlap_tokens, count_tokens)}\n{body}"
            drafts.append(
                draft(
                    body,
                    group[0].subsection,
                    min(u.page_start for u in group),
                    max(u.page_end for u in group),
                )
            )
            previous_text = "\n".join(u.text for u in group)
    return drafts
