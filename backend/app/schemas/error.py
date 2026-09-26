"""The consistent error envelope returned by every failing endpoint."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["The requested resource was not found."])
    request_id: str | None = Field(examples=["3f2b8c1e9a4d4e0f8b6a1c2d3e4f5a6b"])
    details: Any | None = Field(
        default=None, description="Optional structured detail, e.g. validation errors."
    )


class ErrorResponse(BaseModel):
    error: ErrorBody
