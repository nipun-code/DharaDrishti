"""Section-reference parser. Only parsing is tested here: no legal content or mappings."""

import pytest

from app.services.retrieval.section_lookup import parse_section_refs


def refs(query: str) -> list[tuple[str, str, str | None]]:
    return [(r.act_code, r.section, r.subsection) for r in parse_section_refs(query)]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # The three forms named in the spec.
        ("What does IPC 420 say?", [("IPC", "420", None)]),
        ("Explain section 66A of IT Act", [("ITA", "66A", None)]),
        ("BNS s.318 punishment", [("BNS", "318", None)]),
        # Section-first variants.
        ("section 66C of the IT Act", [("ITA", "66C", None)]),
        ("Sec. 420 IPC", [("IPC", "420", None)]),
        ("s 318 BNS", [("BNS", "318", None)]),
        ("under section 35 of the Bharatiya Nagarik Suraksha Sanhita", [("BNSS", "35", None)]),
        ("section 63 of Bharatiya Sakshya Adhiniyam", [("BSA", "63", None)]),
        ("section 43 of the Information Technology Act, 2000", [("ITA", "43", None)]),
        ("Section 318 of BNS, 2023", [("BNS", "318", None)]),
        # Act-first variants.
        ("IPC section 302", [("IPC", "302", None)]),
        ("I.P.C. 420", [("IPC", "420", None)]),
        ("bns 318", [("BNS", "318", None)]),
        ("BNS, 2023 section 318", [("BNS", "318", None)]),
        ("Indian Penal Code 120B", [("IPC", "120B", None)]),
        # Number-first ("420 IPC" is common usage).
        ("case under 420 IPC", [("IPC", "420", None)]),
        ("302 of the IPC", [("IPC", "302", None)]),
        # Letter suffixes and sub-sections.
        ("ipc 498a", [("IPC", "498A", None)]),
        ("BNS 318(4)", [("BNS", "318", "(4)")]),
        ("section 2(1)(a) of BNSS", [("BNSS", "2", "(1)(a)")]),
        ("BNS 318 (4)", [("BNS", "318", "(4)")]),
    ],
)
def test_single_reference_forms(query: str, expected: list[tuple[str, str, str | None]]) -> None:
    assert refs(query) == expected


def test_bnss_is_not_mistaken_for_bns() -> None:
    assert refs("BNSS 35") == [("BNSS", "35", None)]
    assert refs("BNS 35") == [("BNS", "35", None)]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("sections 420 and 406 of IPC", [("IPC", "420", None), ("IPC", "406", None)]),
        ("IPC 420/406", [("IPC", "420", None), ("IPC", "406", None)]),
        ("sections 3, 4 & 5 of BNS", [("BNS", "3", None), ("BNS", "4", None), ("BNS", "5", None)]),
    ],
)
def test_lists_of_sections(query: str, expected: list[tuple[str, str, str | None]]) -> None:
    assert refs(query) == expected


def test_multiple_acts_in_order_of_appearance() -> None:
    assert refs("Compare IPC 420 with BNS 318 and section 66C of IT Act") == [
        ("IPC", "420", None),
        ("BNS", "318", None),
        ("ITA", "66C", None),
    ]


def test_duplicates_removed() -> None:
    assert refs("IPC 420 ... again IPC 420 and section 420 of IPC") == [("IPC", "420", None)]


@pytest.mark.parametrize(
    "query",
    [
        "What is the punishment for cheating under BNS?",  # act, but no section
        "What changed in BNS 2023?",  # a year, not a section
        "Bharatiya Nyaya Sanhita, 2023",
        "Can the police arrest without a warrant?",
        "section 5 says what?",  # no act named
        "Give me 2 IPC sections about theft",  # small count, not a section number
        "the vitamins and minerals",  # "ita"/"ns" inside words
        "This is 420 dollars",
        "Does it act as a deterrent? section 5",
    ],
)
def test_no_false_positives(query: str) -> None:
    assert refs(query) == []


def test_year_allowed_when_section_word_present() -> None:
    # Unusual but explicit: the user literally wrote "section".
    assert refs("section 2000 of IPC") == [("IPC", "2000", None)]


def test_raw_text_and_label_kept() -> None:
    [ref] = parse_section_refs("tell me about ipc s. 420 please")

    assert ref.label == "IPC 420"
    assert "420" in ref.raw
    assert ref.raw.lower().startswith("ipc")
