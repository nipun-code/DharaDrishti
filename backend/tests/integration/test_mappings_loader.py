"""Loading mapping rows into section_mappings. Uses fake act codes, never real mappings."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import CliError, load_mapping_file
from app.core.config import Settings
from app.db.models import SectionMapping
from app.services.ingestion.mappings import MappingRow, load_mappings

pytestmark = pytest.mark.integration


async def all_rows(session: AsyncSession) -> list[tuple[str, str, str, str, str | None]]:
    session.expunge_all()
    result = await session.scalars(select(SectionMapping).order_by(SectionMapping.id))
    return [(m.from_act, m.from_section, m.to_act, m.to_section, m.note) for m in result]


async def test_upsert_is_idempotent_and_updates_notes(db_session: AsyncSession) -> None:
    rows = [MappingRow("OLDACT", "10", "NEWACT", "20", "first")]
    await load_mappings(db_session, rows)

    result = await load_mappings(db_session, [MappingRow("OLDACT", "10", "NEWACT", "20", "second")])

    assert result.upserted == 1
    assert await all_rows(db_session) == [("OLDACT", "10", "NEWACT", "20", "second")]


async def test_replace_deletes_existing_rows(db_session: AsyncSession) -> None:
    await load_mappings(db_session, [MappingRow("OLDACT", "1", "NEWACT", "2", None)])

    result = await load_mappings(
        db_session, [MappingRow("OLDACT", "3", "NEWACT", "4", None)], replace=True
    )

    assert result.deleted == 1
    assert await all_rows(db_session) == [("OLDACT", "3", "NEWACT", "4", None)]


async def test_cli_loader_reads_file_and_reports_errors(
    tmp_path: Path, settings: Settings, test_database_url: str, db_session: AsyncSession
) -> None:
    from pydantic import SecretStr  # noqa: PLC0415

    db_settings = settings.model_copy(update={"database_url": SecretStr(test_database_url)})
    missing = tmp_path / "nope.csv"
    with pytest.raises(CliError, match="not found"):
        await load_mapping_file(db_settings, missing, replace=False)

    bad = tmp_path / "bad.csv"
    bad.write_text("from_act,from_section\nX,1\n", encoding="utf-8")
    with pytest.raises(CliError, match="Missing column"):
        await load_mapping_file(db_settings, bad, replace=False)
