"""Golden evaluation dataset (JSONL), written by the user from the acts themselves.

One JSON object per line:
    {"id": "q001",
     "question": "...",
     "expected_sections": [{"act": "BNS", "section": "318"}],
     "reference_answer": "... (optional)",
     "category": "exact_ref" | "semantic" | "mapping" | "out_of_scope"}

`out_of_scope` rows must have no expected sections (the system should refuse); every other
category needs at least one.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.core.exceptions import BadRequestError
from app.services.catalog import normalize_section

Category = Literal["exact_ref", "semantic", "mapping", "out_of_scope"]
CATEGORIES: tuple[Category, ...] = ("exact_ref", "semantic", "mapping", "out_of_scope")
_MAX_ERRORS = 20


class DatasetError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        shown = errors[:_MAX_ERRORS]
        more = f"\n... and {len(errors) - len(shown)} more" if len(errors) > len(shown) else ""
        super().__init__("Invalid golden dataset:\n" + "\n".join(shown) + more)


class ExpectedSection(BaseModel):
    act: str = Field(min_length=2, max_length=32)
    section: str

    @field_validator("act")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("section")
    @classmethod
    def _section(cls, value: str) -> str:
        # "318(4)" counts as section 318: retrieval works at section level.
        try:
            return normalize_section(value.split("(", 1)[0])
        except BadRequestError as exc:  # surface as a normal validation error for this line
            raise ValueError(exc.message) from exc

    @property
    def key(self) -> tuple[str, str]:
        return self.act, self.section


class GoldenItem(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=3, max_length=1000)
    expected_sections: list[ExpectedSection] = Field(default_factory=list)
    reference_answer: str | None = None
    category: Category

    @model_validator(mode="after")
    def _expected_matches_category(self) -> "GoldenItem":
        if self.category == "out_of_scope" and self.expected_sections:
            raise ValueError("out_of_scope questions must not list expected_sections")
        if self.category != "out_of_scope" and not self.expected_sections:
            raise ValueError(f"{self.category} questions need at least one expected section")
        return self

    @property
    def expected_keys(self) -> set[tuple[str, str]]:
        return {e.key for e in self.expected_sections}


def parse_golden(text: str) -> list[GoldenItem]:
    items: list[GoldenItem] = []
    errors: list[str] = []
    seen: set[str] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        try:
            item = GoldenItem.model_validate(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: not valid JSON ({exc.msg})")
            continue
        except ValidationError as exc:
            detail = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'row'}: {err['msg']}"
                for err in exc.errors()
            )
            errors.append(f"line {line_no}: {detail}")
            continue
        if item.id in seen:
            errors.append(f"line {line_no}: duplicate id {item.id!r}")
            continue
        seen.add(item.id)
        items.append(item)
    if errors:
        raise DatasetError(errors)
    if not items:
        raise DatasetError(["The dataset has no questions."])
    return items


def load_golden(path: Path) -> list[GoldenItem]:
    if not path.is_file():
        raise DatasetError(
            [f"{path} not found. Copy golden.example.jsonl to golden.jsonl and fill it in."]
        )
    return parse_golden(path.read_text(encoding="utf-8"))


def category_counts(items: list[GoldenItem]) -> dict[str, int]:
    counts = Counter(item.category for item in items)
    return {category: counts.get(category, 0) for category in CATEGORIES}
