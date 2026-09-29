"""Detect explicit section references in a query ("IPC 420", "section 66A of IT Act",
"BNS s.318", "420 IPC", "sections 420 and 406 of the Indian Penal Code", "BNS 318(4)").

Only acts listed in ACT_ALIASES are recognised; the codes must match `acts.short_code`
values used at ingestion. A reference to an act that has not been ingested simply finds no
chunks. Act names here are identifiers only; no legal content is encoded.
"""

import re
from collections.abc import Iterable

from app.services.retrieval.types import SectionRef

# code -> ways people write it. Abbreviations match with or without dots ("I.P.C.").
ACT_ALIASES: dict[str, tuple[str, ...]] = {
    "BNS": ("BNS", "Bharatiya Nyaya Sanhita", "Bharatiya Nyay Sanhita"),
    "BNSS": ("BNSS", "Bharatiya Nagarik Suraksha Sanhita"),
    "BSA": ("BSA", "Bharatiya Sakshya Adhiniyam"),
    "IPC": ("IPC", "Indian Penal Code"),
    "ITA": ("ITA", "IT Act", "Information Technology Act"),
}

_YEAR_RE = re.compile(r"^(?:18|19|20)\d{2}$")


def _alias_pattern(alias: str) -> str:
    words = []
    for word in alias.split():
        if word.isupper() and len(word) > 1:  # abbreviation: optional dot after each letter
            words.append("".join(f"{re.escape(ch)}\\.?" for ch in word))
        else:
            words.append(re.escape(word))
    return r"\s+".join(words)


def _normalize_alias(text: str) -> str:
    return re.sub(r"[\s.]", "", text).lower()


_ALIAS_TO_CODE = {
    _normalize_alias(alias): code for code, aliases in ACT_ALIASES.items() for alias in aliases
}
# Longest first, so "BNSS" wins over "BNS" and "IT Act" over "ITA".
_ALIAS = (
    r"(?P<act>"
    + "|".join(
        _alias_pattern(a)
        for a in sorted((a for al in ACT_ALIASES.values() for a in al), key=len, reverse=True)
    )
    + r")(?![A-Za-z])"
)
_YEAR = r"(?:\s*,?\s*(?:18|19|20)\d{2}\b)?"
_ACT_NAME_RE = re.compile(rf"\b{_ALIAS}{_YEAR}", re.IGNORECASE)
_NUM = r"\d{1,4}[A-Za-z]{0,3}(?:\s*\(\s*[0-9A-Za-z]{1,4}\s*\))*"
_NUMLIST = rf"(?P<nums>{_NUM}(?:\s*(?:,|/|&|\band\b|\bor\b)\s*{_NUM})*)"
_SEC = r"(?P<sec>\b(?:sections?|secs?|ss?)\.?)"
_CONNECTOR = r"(?:\s*,?\s*(?:of|under|in)\b)?\s*(?:the\s+)?"

_PATTERNS = [
    # "section 66A of the IT Act", "s.318 BNS", "sections 420 and 406 of IPC"
    re.compile(rf"{_SEC}\s*{_NUMLIST}{_CONNECTOR}\b{_ALIAS}{_YEAR}", re.IGNORECASE),
    # "IPC 420", "BNS s.318", "IPC section 420", "BNS, 2023 section 318", "IPC 420/406"
    re.compile(rf"\b{_ALIAS}{_YEAR}\s*,?\s*(?:{_SEC}\s*)?{_NUMLIST}", re.IGNORECASE),
    # "420 IPC", "302 of the IPC" (at least 2 digits, to avoid "2 IPC sections")
    re.compile(rf"\b(?P<nums>\d{{2,4}}[A-Za-z]{{0,3}}){_CONNECTOR}\b{_ALIAS}", re.IGNORECASE),
]
_SPLIT_NUMS_RE = re.compile(r"\s*(?:,|/|&|\band\b|\bor\b)\s*", re.IGNORECASE)
_BASE_RE = re.compile(r"^(?P<base>\d{1,4}[A-Za-z]{0,3})(?P<sub>(?:\([0-9A-Za-z]{1,4}\))*)$")


def _split_section(token: str) -> tuple[str, str | None] | None:
    match = _BASE_RE.match(re.sub(r"\s+", "", token))
    if not match:
        return None
    base = match.group("base")
    digits = len(base) - len(base.lstrip("0123456789"))
    base = base[:digits] + base[digits:].upper()
    sub = match.group("sub")
    # Clause letters inside brackets stay lower case: "(1)(a)".
    return base, (sub.lower() if sub else None)


def parse_section_refs(query: str) -> list[SectionRef]:
    """Return explicit section references in order of appearance, de-duplicated."""
    found: list[tuple[int, SectionRef]] = []
    taken: list[tuple[int, int]] = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(query):
            start, end = match.span()
            if any(start < t_end and t_start < end for t_start, t_end in taken):
                continue  # overlaps a match from a more specific pattern
            code = _ALIAS_TO_CODE.get(_normalize_alias(match.group("act")))
            if code is None:
                continue
            has_section_word = bool(match.groupdict().get("sec"))
            refs = list(_refs(code, match.group("nums"), match.group(0), has_section_word))
            if refs:
                taken.append((start, end))
                found.extend((start, ref) for ref in refs)

    unique: dict[tuple[str, str, str | None], SectionRef] = {}
    for _, ref in sorted(found, key=lambda item: item[0]):
        unique.setdefault((ref.act_code, ref.section, ref.subsection), ref)
    return list(unique.values())


def _refs(code: str, nums: str, raw: str, has_section_word: bool) -> Iterable[SectionRef]:
    for token in _SPLIT_NUMS_RE.split(nums.strip()):
        parts = _split_section(token)
        if parts is None:
            continue
        base, sub = parts
        # "BNS 2023" is the act's year, not section 2023 (unless "section" was written).
        if not has_section_word and not sub and _YEAR_RE.match(base):
            continue
        yield SectionRef(act_code=code, section=base, subsection=sub, raw=raw.strip())


def strip_act_names(text: str) -> str:
    """Remove act names/codes ("BNS", "Indian Penal Code, 1860") from a search phrase.

    Full-text search ANDs every word, and act codes never appear in section text, so
    "punishment for theft in BNS" would match nothing. Returns `text` unchanged if nothing
    would be left."""
    stripped = " ".join(_ACT_NAME_RE.sub(" ", text).split())
    return stripped or text
