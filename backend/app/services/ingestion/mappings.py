"""Load the user-provided, verified IPC -> BNS mapping table (data/mappings/ipc_bns.csv).

Expected header (exactly these columns, in any order):
    from_act,from_section,to_act,to_section,note

Rows are validated up front; nothing is written unless the whole file is valid. Loading is an
upsert on (from_act, from_section, to_act, to_section), so re-running it is safe.
"""

import csv
import io
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.section_mappings import SectionMappingRepository

REQUIRED_COLUMNS = ("from_act", "from_section", "to_act", "to_section", "note")
ACT_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
# "420", "120B", "66C", optionally with sub-section parts: "318(4)", "2(1)(a)".
SECTION_RE = re.compile(r"^\d{1,4}[A-Z]{0,3}(?:\([0-9A-Za-z]{1,4}\))*$")
_MAX_ERRORS_REPORTED = 20


class MappingFileError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        shown = errors[:_MAX_ERRORS_REPORTED]
        more = f"\n... and {len(errors) - len(shown)} more" if len(errors) > len(shown) else ""
        super().__init__("Invalid mapping file:\n" + "\n".join(shown) + more)


@dataclass(frozen=True, slots=True)
class MappingRow:
    from_act: str
    from_section: str
    to_act: str
    to_section: str
    note: str | None


@dataclass(frozen=True, slots=True)
class LoadResult:
    rows_in_file: int
    upserted: int
    deleted: int


def _clean_section(value: str) -> str:
    # Uppercase the letter suffix ("66c" -> "66C") but keep clause letters "(a)" lower case.
    head, sep, tail = value.strip().replace(" ", "").partition("(")
    return head.upper() + sep + tail


def parse_mapping_csv(text: str) -> list[MappingRow]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise MappingFileError([f"Missing column(s): {', '.join(missing)}. Header: {header}"])
    reader.fieldnames = header

    rows: dict[tuple[str, str, str, str], MappingRow] = {}
    errors: list[str] = []
    for line_no, raw in enumerate(reader, start=2):
        values = {k: (raw.get(k) or "").strip() for k in REQUIRED_COLUMNS}
        if not any(values.values()):
            continue  # blank line
        row = MappingRow(
            from_act=values["from_act"].upper(),
            from_section=_clean_section(values["from_section"]),
            to_act=values["to_act"].upper(),
            to_section=_clean_section(values["to_section"]),
            note=values["note"] or None,
        )
        problems = [
            f"{field} {value!r} is not a valid act code"
            for field, value in (("from_act", row.from_act), ("to_act", row.to_act))
            if not ACT_RE.match(value)
        ] + [
            f"{field} {value!r} is not a valid section number"
            for field, value in (("from_section", row.from_section), ("to_section", row.to_section))
            if not SECTION_RE.match(value)
        ]
        if problems:
            errors.append(f"line {line_no}: " + "; ".join(problems))
            continue
        rows[(row.from_act, row.from_section, row.to_act, row.to_section)] = row  # last wins

    if errors:
        raise MappingFileError(errors)
    if not rows:
        raise MappingFileError(["The file contains no mapping rows."])
    return list(rows.values())


async def load_mappings(
    session: AsyncSession, rows: list[MappingRow], *, replace: bool = False
) -> LoadResult:
    """Upsert rows in one transaction. With replace=True, existing mappings are deleted first."""
    repo = SectionMappingRepository(session)
    deleted = await repo.delete_all() if replace else 0
    await repo.upsert_many(
        [
            {
                "from_act": r.from_act,
                "from_section": r.from_section,
                "to_act": r.to_act,
                "to_section": r.to_section,
                "note": r.note,
            }
            for r in rows
        ]
    )
    await session.commit()
    return LoadResult(rows_in_file=len(rows), upserted=len(rows), deleted=deleted)
