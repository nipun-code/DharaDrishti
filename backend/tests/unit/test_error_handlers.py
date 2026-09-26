import httpx
import pytest
from fastapi import FastAPI

from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError


@pytest.fixture
def app_with_routes(app: FastAPI) -> FastAPI:
    async def not_found() -> None:
        raise NotFoundError("Section not found.")

    async def conflict() -> None:
        raise ConflictError(details={"sha256": "abc"})

    async def unavailable() -> None:
        raise ServiceUnavailableError

    async def boom() -> None:
        raise RuntimeError("internal secret detail")

    async def typed(limit: int) -> dict[str, int]:
        return {"limit": limit}

    app.add_api_route("/_test/not-found", not_found)
    app.add_api_route("/_test/conflict", conflict)
    app.add_api_route("/_test/unavailable", unavailable)
    app.add_api_route("/_test/boom", boom)
    app.add_api_route("/_test/typed", typed)
    return app


def assert_envelope(response: httpx.Response, status: int, code: str) -> dict[str, object]:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert error["message"]
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error  # type: ignore[no-any-return]


@pytest.mark.usefixtures("app_with_routes")
async def test_app_error_uses_envelope(client: httpx.AsyncClient) -> None:
    error = assert_envelope(await client.get("/_test/not-found"), 404, "not_found")
    assert error["message"] == "Section not found."
    assert "details" not in error


@pytest.mark.usefixtures("app_with_routes")
async def test_app_error_default_message_and_details(client: httpx.AsyncClient) -> None:
    error = assert_envelope(await client.get("/_test/conflict"), 409, "conflict")
    assert error["details"] == {"sha256": "abc"}


@pytest.mark.usefixtures("app_with_routes")
async def test_server_side_app_error(client: httpx.AsyncClient) -> None:
    assert_envelope(await client.get("/_test/unavailable"), 503, "service_unavailable")


@pytest.mark.usefixtures("app_with_routes")
async def test_unhandled_exception_returns_500_without_leaking(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/boom")

    error = assert_envelope(response, 500, "internal_error")
    assert "secret" not in response.text
    assert "Traceback" not in response.text
    assert error["message"] == "An unexpected error occurred."


async def test_unknown_route_returns_404_envelope(client: httpx.AsyncClient) -> None:
    assert_envelope(await client.get("/does-not-exist"), 404, "not_found")


async def test_wrong_method_returns_405_envelope(client: httpx.AsyncClient) -> None:
    assert_envelope(await client.post("/health/live"), 405, "method_not_allowed")


@pytest.mark.usefixtures("app_with_routes")
async def test_validation_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/typed", params={"limit": "not-a-number"})

    error = assert_envelope(response, 422, "validation_error")
    details = error["details"]
    assert isinstance(details, list)
    assert details[0]["loc"] == ["query", "limit"]
    assert "input" not in details[0]
