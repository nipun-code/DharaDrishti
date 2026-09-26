import httpx
from fastapi import FastAPI

from tests.conftest import FakeProbe, override_probes


async def test_live_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_ok_when_all_dependencies_up(app: FastAPI, client: httpx.AsyncClient) -> None:
    override_probes(app, FakeProbe("database"), FakeProbe("redis"))

    response = await client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"database", "redis"}
    for check in body["checks"].values():
        assert check["status"] == "ok"
        assert check["error"] is None
        assert check["latency_ms"] >= 0


async def test_ready_503_when_a_dependency_fails(app: FastAPI, client: httpx.AsyncClient) -> None:
    override_probes(
        app,
        FakeProbe("database", error=ConnectionRefusedError("secret-host:5432 refused")),
        FakeProbe("redis"),
    )

    response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] == {
        "status": "error",
        "latency_ms": body["checks"]["database"]["latency_ms"],
        "error": "unreachable",
    }
    assert body["checks"]["redis"]["status"] == "ok"
    # Internal error details must never leak into the response.
    assert "secret-host" not in response.text


async def test_ready_503_on_timeout(app: FastAPI, client: httpx.AsyncClient) -> None:
    override_probes(app, FakeProbe("database"), FakeProbe("redis", delay=1), timeout=0.05)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["redis"]["error"] == "timeout"


async def test_health_responses_carry_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")

    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert len(request_id) == 32


async def test_valid_incoming_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "abc-123.XYZ_9"})

    assert response.headers["X-Request-ID"] == "abc-123.XYZ_9"


async def test_unsafe_incoming_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "bad id\twith spaces"})

    assert response.headers["X-Request-ID"] != "bad id\twith spaces"
    assert len(response.headers["X-Request-ID"]) == 32
