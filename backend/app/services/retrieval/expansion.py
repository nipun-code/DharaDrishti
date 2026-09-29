"""Whole-section context: turn ranked chunks into one source per section.

Long sections are stored as several pieces, and search usually finds only one of them, so the
answer can miss the part that matters (e.g. the punishment clause after a run of
Illustrations). Before generation, each retrieved section is re-read in full and its pieces are
joined in order, with the overlap the chunker copied onto each later piece removed.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from itertools import pairwise

from app.services.retrieval.search import SearchBackend
from app.services.retrieval.types import Candidate, ChunkRecord


def join_pieces(pieces: Sequence[ChunkRecord]) -> ChunkRecord:
    """Merge the pieces of one section (in stored order) into a single record.

    Every piece after the first starts with a line holding the tail of the previous piece; that
    line is dropped when it really is the previous piece's tail."""
    first = pieces[0]
    texts = [first.text]
    for prev, piece in pairwise(pieces):
        head, sep, rest = piece.text.partition("\n")
        overlap = head.split()
        if sep and overlap and prev.text.split()[-len(overlap) :] == overlap:
            texts.append(rest)
        else:
            texts.append(piece.text)
    starts = [p.page_start for p in pieces if p.page_start is not None]
    ends = [p.page_end for p in pieces if p.page_end is not None]
    return replace(
        first,
        text="\n".join(texts),
        subsection=None,
        page_start=min(starts) if starts else None,
        page_end=max(ends) if ends else None,
    )


async def expand_sections(
    backend: SearchBackend, candidates: Sequence[Candidate], max_pieces: int
) -> list[Candidate]:
    """One candidate per (act, section), in rank order, carrying the whole section's text.

    The best-ranked candidate of each section keeps its scores and chunk id; its text becomes
    the joined section. Sections with a single stored piece are returned unchanged."""
    best: dict[tuple[str, str], Candidate] = {}
    for candidate in candidates:
        best.setdefault((candidate.chunk.act_code, candidate.chunk.section_number), candidate)
    keys = list(best)
    pieces = await asyncio.gather(
        *(backend.section(act, section, None, max_pieces) for act, section in keys)
    )
    expanded: list[Candidate] = []
    for key, section_pieces in zip(keys, pieces, strict=True):
        candidate = best[key]
        if len(section_pieces) > 1:
            joined = join_pieces(section_pieces)
            candidate = replace(candidate, chunk=replace(joined, id=candidate.chunk.id))
        expanded.append(candidate)
    return expanded
