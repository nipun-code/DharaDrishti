"""System guardrails (rate limits, token budget, CORS, security headers), the answer cache and
the output-verification helpers — each with passing and blocked cases."""

import uuid
from typing import Any

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Settings
from app.core.exceptions import RateLimitedError, TokenBudgetExceededError
from app.services.cache.exact import AnswerCache, cache_key
from app.services.generation.llm_tasks import parse_json_object
from app.services.guardrails.output import mentioned_sections, verify_citations
from app.services.limits import RateLimiter, TokenBudget
from tests.conftest import FakeRedis


class BrokenRedis(FakeRedis):
    async def get(self, key: str) -> Any:
        raise RedisConnectionError("down")

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        raise RedisConnectionError("down")

    async def incrby(self, key: str, amount: int) -> int:
        raise RedisConnectionError("down")


# ---------------------------------------------------------------- rate limiting
async def test_rate_limit_allows_up_to_limit_then_blocks() -> None:
    limiter = RateLimiter(FakeRedis(), now=lambda: 1000.0)  # type: ignore[arg-type]

    for _ in range(3):
        await limiter.hit("user:1", limit=3)
    with pytest.raises(RateLimitedError) as info:
        await limiter.hit("user:1", limit=3)

    assert info.value.status_code == 429
    assert info.value.headers == {"Retry-After": "20"}  # window ends at t=1020


async def test_rate_limit_keys_and_windows_are_independent() -> None:
    clock = [1000.0]
    limiter = RateLimiter(FakeRedis(), now=lambda: clock[0])  # type: ignore[arg-type]
    await limiter.hit("user:1", limit=1)

    await limiter.hit("user:2", limit=1)  # other user: allowed
    clock[0] = 1061.0  # next minute
    await limiter.hit("user:1", limit=1)  # allowed again


async def test_rate_limit_fails_open_when_redis_is_down() -> None:
    limiter = RateLimiter(BrokenRedis())  # type: ignore[arg-type]

    await limiter.hit("user:1", limit=0)  # no exception


# ---------------------------------------------------------------- token budget
async def test_token_budget_blocks_when_exhausted() -> None:
    budget = TokenBudget(FakeRedis(), daily_limit=100)  # type: ignore[arg-type]
    user = uuid.uuid4()

    await budget.check(user)
    await budget.add(user, 60)
    await budget.check(user)  # 60 < 100: allowed
    await budget.add(user, 40)

    with pytest.raises(TokenBudgetExceededError, match="resets at 00:00 UTC"):
        await budget.check(user)
    assert await budget.used(user) == 100


async def test_token_budget_is_per_user_and_ignores_zero() -> None:
    redis = FakeRedis()
    budget = TokenBudget(redis, daily_limit=10)  # type: ignore[arg-type]
    a, b = uuid.uuid4(), uuid.uuid4()
    await budget.add(a, 10)
    await budget.add(b, 0)

    await budget.check(b)
    assert await budget.used(b) == 0
    assert all(v == 2 * 24 * 3600 for v in redis.expiries.values())


async def test_token_budget_fails_open() -> None:
    budget = TokenBudget(BrokenRedis(), daily_limit=1)  # type: ignore[arg-type]

    await budget.check(uuid.uuid4())
    await budget.add(uuid.uuid4(), 5)


# ---------------------------------------------------------------- answer cache
def test_cache_key_normalizes_query_and_filters() -> None:
    base = cache_key("What is BNS 318?", ["bns", "ipc"], "hybrid_rerank", 5)

    assert base == cache_key("  what IS   bns 318? ", ["IPC", "BNS"], "hybrid_rerank", 5)
    assert base != cache_key("What is BNS 318?", ["BNS"], "hybrid_rerank", 5)
    assert base != cache_key("What is BNS 318?", ["bns", "ipc"], "hybrid", 5)
    assert base != cache_key("What is BNS 318?", ["bns", "ipc"], "hybrid_rerank", 3)
    assert base.startswith("qa:v1:")


async def test_cache_roundtrip_and_ttl() -> None:
    redis = FakeRedis()
    cache = AnswerCache(redis, ttl_seconds=123)  # type: ignore[arg-type]

    assert await cache.get("k") is None
    await cache.set("k", {"answer": "a [1]"})

    assert await cache.get("k") == {"answer": "a [1]"}
    assert redis.expiries["k"] == 123


async def test_cache_disabled_and_corrupt_values() -> None:
    redis = FakeRedis()
    disabled = AnswerCache(redis, ttl_seconds=1, enabled=False)  # type: ignore[arg-type]
    await disabled.set("k", {"a": 1})
    assert redis.data == {}
    assert await disabled.get("k") is None

    redis.data["bad"] = "{not json"
    redis.data["list"] = "[1, 2]"
    cache = AnswerCache(redis, ttl_seconds=1)  # type: ignore[arg-type]
    assert await cache.get("bad") is None
    assert await cache.get("list") is None


async def test_cache_errors_never_raise() -> None:
    cache = AnswerCache(BrokenRedis(), ttl_seconds=1)  # type: ignore[arg-type]

    assert await cache.get("k") is None
    await cache.set("k", {"a": 1})


# ---------------------------------------------------------------- output helpers
def test_verify_citations_keeps_valid_drops_invalid() -> None:
    check = verify_citations("A [1]. B [2, 5]. C [3] [4]", source_count=3)

    assert check.text == "A [1]. B [2]. C [3]"
    assert check.cited == (1, 2, 3)
    assert check.invalid == (5, 4)


def test_verify_citations_with_nothing_valid() -> None:
    check = verify_citations("No sources here.", source_count=3)

    assert check.cited == ()
    assert check.text == "No sources here."


def test_mentioned_sections_parses_common_forms() -> None:
    text = (
        "Section 318(4) and sections 420, 406 & 409; s. 66C; ss. 3 to 5. "
        "Also section 318 again and 2023 as a year."
    )

    assert mentioned_sections(text) == ["318", "420", "406", "409", "66C", "3", "5"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Sure! {"a": 1} hope this helps', {"a": 1}),
        ("[1, 2]", None),
        ("nothing", None),
    ],
)
def test_parse_json_object(text: str, expected: dict[str, int] | None) -> None:
    assert parse_json_object(text) == expected


# ---------------------------------------------------------------- HTTP: headers & CORS
async def test_security_headers_on_api_responses(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in response.headers  # only in production


async def test_docs_page_not_blocked_by_csp(client: httpx.AsyncClient) -> None:
    response = await client.get("/docs")

    assert "Content-Security-Policy" not in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_hsts_in_production(settings: Settings) -> None:
    from app.main import create_app  # noqa: PLC0415

    app = create_app(settings.model_copy(update={"environment": "production"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        response = await c.get("/health/live")

    assert response.headers["Strict-Transport-Security"].startswith("max-age=")


async def test_cors_allows_configured_frontend_origin(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/api/v1/query",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_cors_rejects_other_origins(client: httpx.AsyncClient) -> None:
    preflight = await client.options(
        "/api/v1/query",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    simple = await client.get("/health/live", headers={"Origin": "https://evil.example"})

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in simple.headers


async def test_security_headers_also_on_cors_preflight(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/api/v1/query",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Request-ID"]
