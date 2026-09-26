from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.health import DatabaseProbe, RedisProbe
from app.services.health import HealthService
from tests.conftest import FakeProbe


async def test_all_probes_ok() -> None:
    service = HealthService([FakeProbe("a"), FakeProbe("b")], timeout_seconds=1)

    report = await service.check_readiness()

    assert report.is_ready
    assert report.status == "ok"
    assert list(report.checks) == ["a", "b"]


async def test_one_failure_makes_service_unready() -> None:
    service = HealthService([FakeProbe("a"), FakeProbe("b", error=OSError())], timeout_seconds=1)

    report = await service.check_readiness()

    assert not report.is_ready
    assert report.checks["a"].status == "ok"
    assert report.checks["b"].status == "error"
    assert report.checks["b"].error == "unreachable"


async def test_slow_probe_times_out() -> None:
    service = HealthService([FakeProbe("slow", delay=1)], timeout_seconds=0.01)

    report = await service.check_readiness()

    assert report.checks["slow"].error == "timeout"


async def test_no_probes_is_ready() -> None:
    report = await HealthService([], timeout_seconds=1).check_readiness()

    assert report.is_ready
    assert report.checks == {}


async def test_redis_probe_pings_client() -> None:
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)

    await RedisProbe(client).ping()

    client.ping.assert_awaited_once()


async def test_redis_probe_propagates_errors() -> None:
    client = MagicMock()
    client.ping = AsyncMock(side_effect=ConnectionError("down"))

    with pytest.raises(ConnectionError):
        await RedisProbe(client).ping()


async def test_database_probe_executes_select_1() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    engine = MagicMock()
    engine.connect.return_value = ctx

    await DatabaseProbe(engine).ping()

    conn.execute.assert_awaited_once()
    assert str(conn.execute.await_args.args[0]) == "SELECT 1"
