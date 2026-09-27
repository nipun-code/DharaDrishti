"""Value types shared by the ingestion stages."""

from dataclasses import dataclass


class IngestionError(Exception):
    """An expected ingestion failure. The message is user-safe and stored on the document."""


@dataclass(frozen=True, slots=True)
class PageText:
    number: int  # 1-based page number in the source PDF
    text: str


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """One retrievable piece of a section, before embedding."""

    act_code: str
    chapter_number: str | None
    chapter_title: str | None
    section_number: str
    section_title: str
    subsection: str | None
    text: str
    page_start: int
    page_end: int
    token_count: int

    @property
    def context_header(self) -> str:
        """e.g. "[ACT | Chapter II: Of Things | Section 5: Heading]" (contextual retrieval)."""
        parts = [self.act_code]
        if self.chapter_number:
            chapter = f"Chapter {self.chapter_number}"
            if self.chapter_title:
                chapter += f": {self.chapter_title}"
            parts.append(chapter)
        section = f"Section {self.section_number}"
        if self.section_title:
            section += f": {self.section_title}"
        parts.append(section)
        return "[" + " | ".join(parts) + "]"

    @property
    def embedding_text(self) -> str:
        """What gets embedded: the context header followed by the chunk text."""
        return f"{self.context_header}\n{self.text}"
