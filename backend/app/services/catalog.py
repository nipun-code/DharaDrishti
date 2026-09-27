"""Read-side views used by the UI: acts, full section text, IPC -> BNS mapping; and feedback."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models import Feedback, QueryLog, SectionMapping
from app.repositories.acts import ActRepository
from app.repositories.chunk_search import ChunkSearchRepository
from app.repositories.feedback import FeedbackRepository
from app.schemas.catalog import (
    ActSummary,
    FeedbackRead,
    FeedbackRequest,
    MappingTarget,
    MappingView,
    SectionView,
)
from app.services.retrieval.types import ChunkRecord

_SECTION_RE = re.compile(r"^(\d{1,4})([A-Za-z]{0,3})$")
_MAX_PIECES = 50


def normalize_section(raw: str) -> str:
    match = _SECTION_RE.match(raw.strip())
    if not match:
        raise BadRequestError(f"'{raw}' is not a valid section number (e.g. 318, 66C).")
    return match.group(1) + match.group(2).upper()


def _merge_pieces(pieces: list[ChunkRecord]) -> str:
    """Rebuild a section split into overlapping chunks: each later piece starts with a line
    repeating the end of the previous piece, which is dropped here."""
    merged = pieces[0].text
    for piece in pieces[1:]:
        first, _, rest = piece.text.partition("\n")
        if rest and merged.rstrip().endswith(first.strip()):
            merged = f"{merged}\n{rest}"
        else:
            merged = f"{merged}\n{piece.text}"
    return merged


class CatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_acts(self) -> list[ActSummary]:
        rows = await ActRepository(self._session).list_with_chunk_counts()
        return [
            ActSummary(
                short_code=act.short_code,
                full_name=act.full_name,
                year=act.year,
                status=act.status,
                chunks_count=count,
            )
            for act, count in rows
        ]

    async def find_section(self, act_code: str, section: str) -> SectionView | None:
        act = await ActRepository(self._session).get_by_short_code(act_code.upper())
        if act is None:
            return None
        pieces = await ChunkSearchRepository(self._session).section_chunks(
            act.short_code, section, None, _MAX_PIECES
        )
        if not pieces:
            return None
        first = pieces[0]
        return SectionView(
            act=act.short_code,
            act_name=act.full_name,
            act_status=act.status,
            section_number=first.section_number,
            section_title=first.section_title,
            chapter_number=first.chapter_number,
            chapter_title=first.chapter_title,
            text=_merge_pieces(pieces),
            page_start=min((p.page_start for p in pieces if p.page_start), default=None),
            page_end=max((p.page_end for p in pieces if p.page_end), default=None),
        )

    async def get_section(self, act_code: str, raw_section: str) -> SectionView:
        section = normalize_section(raw_section)
        view = await self.find_section(act_code, section)
        if view is None:
            raise NotFoundError(
                f"Section {section} of {act_code.upper()} is not in the indexed acts."
            )
        return view

    async def ipc_mapping(self, raw_section: str) -> MappingView:
        section = normalize_section(raw_section)
        rows = list(
            await self._session.scalars(
                select(SectionMapping)
                .where(
                    SectionMapping.from_act == "IPC",
                    (SectionMapping.from_section == section)
                    | SectionMapping.from_section.like(f"{section}(%"),
                )
                .order_by(SectionMapping.id)
            )
        )
        source = await self.find_section("IPC", section)
        if not rows and source is None:
            raise NotFoundError(
                f"No mapping found for IPC section {section}. "
                "Check that data/mappings/ipc_bns.csv has been loaded."
            )
        targets = []
        for row in rows:
            base = row.to_section.split("(", 1)[0]
            targets.append(
                MappingTarget(
                    to_act=row.to_act,
                    to_section=row.to_section,
                    note=row.note,
                    section=await self.find_section(row.to_act, base),
                )
            )
        return MappingView(from_act="IPC", from_section=section, source=source, targets=targets)


class FeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def submit(self, user_id: uuid.UUID, body: FeedbackRequest) -> FeedbackRead:
        log = await self._session.get(QueryLog, body.query_log_id)
        if log is None or log.user_id != user_id:
            raise NotFoundError("That answer was not found.")
        repo = FeedbackRepository(self._session)
        feedback = await repo.get_for_user(body.query_log_id, user_id)
        if feedback is None:
            feedback = await repo.add(
                Feedback(
                    query_log_id=body.query_log_id,
                    user_id=user_id,
                    rating=body.rating,
                    comment=body.comment,
                )
            )
        else:  # one vote per answer: a new vote replaces the old one
            feedback.rating = body.rating
            feedback.comment = body.comment
        await self._session.commit()
        await self._session.refresh(feedback)
        return FeedbackRead(
            id=feedback.id,
            query_log_id=feedback.query_log_id,
            rating=feedback.rating,
            comment=feedback.comment,
            created_at=feedback.created_at,
        )
