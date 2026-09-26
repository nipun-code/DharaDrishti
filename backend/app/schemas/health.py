"""Health check response schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class DependencyCheck(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float = Field(ge=0)
    error: str | None = Field(
        default=None, description="Short, non-sensitive reason, e.g. 'timeout' or 'unreachable'."
    )


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, DependencyCheck]

    @property
    def is_ready(self) -> bool:
        return self.status == "ok"
