"""Mapping CSV parsing. Rows use fake act codes (OLDACT/NEWACT): no real IPC->BNS mappings."""

import pytest

from app.services.ingestion.mappings import MappingFileError, MappingRow, parse_mapping_csv

HEADER = "from_act,from_section,to_act,to_section,note\n"


def test_parses_and_normalizes_rows() -> None:
    text = HEADER + "oldact, 10 ,newact,20,first\nOLDACT,11a,NEWACT,21(2)(b),\n"

    rows = parse_mapping_csv(text)

    assert rows == [
        MappingRow("OLDACT", "10", "NEWACT", "20", "first"),
        MappingRow("OLDACT", "11A", "NEWACT", "21(2)(b)", None),
    ]


def test_columns_may_be_reordered_and_bom_is_ignored() -> None:
    text = "﻿note,to_section,to_act,from_section,from_act\nx,20,NEWACT,10,OLDACT\n"

    assert parse_mapping_csv(text) == [MappingRow("OLDACT", "10", "NEWACT", "20", "x")]


def test_blank_lines_skipped_and_duplicates_collapsed() -> None:
    text = HEADER + "OLDACT,10,NEWACT,20,a\n,,,,\nOLDACT,10,NEWACT,20,b\n"

    assert parse_mapping_csv(text) == [MappingRow("OLDACT", "10", "NEWACT", "20", "b")]


def test_one_to_many_mappings_kept() -> None:
    text = HEADER + "OLDACT,10,NEWACT,20,\nOLDACT,10,NEWACT,21,\n"

    assert [r.to_section for r in parse_mapping_csv(text)] == ["20", "21"]


def test_missing_column_reported() -> None:
    with pytest.raises(MappingFileError, match="Missing column"):
        parse_mapping_csv("from_act,from_section,to_act\nA,1,B\n")


def test_invalid_rows_reported_with_line_numbers() -> None:
    text = HEADER + "OLDACT,10,NEWACT,20,\n1BAD,x10,NEWACT,,\n"

    with pytest.raises(MappingFileError) as info:
        parse_mapping_csv(text)

    [error] = info.value.errors
    assert error.startswith("line 3:")
    assert "from_act '1BAD'" in error
    assert "from_section 'X10'" in error
    assert "to_section ''" in error


def test_many_errors_are_truncated_in_message() -> None:
    text = HEADER + "".join("bad!,1,NEWACT,2,\n" for _ in range(30))

    with pytest.raises(MappingFileError) as info:
        parse_mapping_csv(text)

    assert len(info.value.errors) == 30
    assert "and 10 more" in str(info.value)


def test_empty_file_rejected() -> None:
    with pytest.raises(MappingFileError, match="no mapping rows"):
        parse_mapping_csv(HEADER)
