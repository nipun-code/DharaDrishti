"""Output guardrails (SPEC §8.3): citation and section-number verification."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

CITATION_RE = re.compile(r"\[\s*(\d{1,3}(?:\s*,\s*\d{1,3})*)\s*\]")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?])")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

_SECTION_NUM = r"\d{1,4}[A-Za-z]{0,3}(?:\s*\(\s*[0-9A-Za-z]{1,4}\s*\))*"
SECTION_MENTION_RE = re.compile(
    rf"\b(?:sections?|secs?\.?|ss?\.)\s*(?P<nums>{_SECTION_NUM}"
    rf"(?:\s*(?:,|/|&|\band\b|\bor\b|\bto\b)\s*{_SECTION_NUM})*)",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(r"\s*(?:,|/|&|\band\b|\bor\b|\bto\b)\s*", re.IGNORECASE)
_BASE_RE = re.compile(r"^(\d{1,4}[A-Za-z]{0,3})")


@dataclass(frozen=True, slots=True)
class CitationCheck:
    text: str  # answer with invalid citation markers removed
    cited: tuple[int, ...]  # valid source numbers, in order of first use
    invalid: tuple[int, ...]  # removed numbers


def verify_citations(answer: str, source_count: int) -> CitationCheck:
    cited: list[int] = []
    invalid: list[int] = []

    def replace(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.split(r"\s*,\s*", match.group(1))]
        valid = [n for n in numbers if 1 <= n <= source_count]
        invalid.extend(n for n in numbers if n not in valid)
        for n in valid:
            if n not in cited:
                cited.append(n)
        return "".join(f"[{n}]" for n in dict.fromkeys(valid))

    text = CITATION_RE.sub(replace, answer)
    if invalid:
        text = _MULTI_SPACE_RE.sub(" ", _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text))
    return CitationCheck(text=text.strip(), cited=tuple(cited), invalid=tuple(invalid))


def mentioned_sections(answer: str) -> list[str]:
    """Base section numbers mentioned as "Section X", "sections X and Y", "s. X", "ss. X to Y"."""
    found: dict[str, None] = {}
    for match in SECTION_MENTION_RE.finditer(answer):
        for token in _SPLIT_RE.split(match.group("nums")):
            base = _BASE_RE.match(token.replace(" ", ""))
            if base:
                number = base.group(1)
                digits = len(number) - len(number.lstrip("0123456789"))
                found[number[:digits] + number[digits:].upper()] = None
    return list(found)


def unverified_sections(mentioned: Iterable[str], known: set[str]) -> list[str]:
    return [number for number in mentioned if number not in known]
