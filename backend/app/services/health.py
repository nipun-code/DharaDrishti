"""Readiness evaluation: probe every dependency concurrently, each bounded by a timeout."""

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Literal

from app.repositories.health import DependencyProbe
from app.schemas.health import DependencyCheck, ReadinessResponse

logger = logging.getLogger(__name__)


class HealthService:
    def __init__(self, probes: Sequence[DependencyProbe], timeout_seconds: float) -> None:
        self._probes = probes
        self._timeout_seconds = timeout_seconds

    async def check_readiness(self) -> ReadinessResponse:
        results = await asyncio.gather(*(self._run_probe(probe) for probe in self._probes))
        checks = dict(results)
        all_ok = all(check.status == "ok" for check in checks.values())
        return ReadinessResponse(status="ok" if all_ok else "unavailable", checks=checks)

    async def _run_probe(self, probe: DependencyProbe) -> tuple[str, DependencyCheck]:
        started = time.perf_counter()
        error: str | None = None
        try:
            await asyncio.wait_for(probe.ping(), timeout=self._timeout_seconds)
        except TimeoutError:
            error = "timeout"
            logger.warning("readiness_probe_timeout", extra={"dependency": probe.name})
        except Exception:  # any failure means "not ready"; details go to logs only
            error = "unreachable"
            logger.warning(
                "readiness_probe_failed", extra={"dependency": probe.name}, exc_info=True
            )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        status: Literal["ok", "error"] = "ok" if error is None else "error"
        return probe.name, DependencyCheck(status=status, latency_ms=latency_ms, error=error)
