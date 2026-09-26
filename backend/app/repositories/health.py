"""Low-level connectivity probes for the infrastructure the app depends on."""

from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DependencyProbe(Protocol):
    """Anything that can verify a dependency is reachable. `ping` raises on failure."""

    @property
    def name(self) -> str: ...

    async def ping(self) -> None: ...


class DatabaseProbe:
    name = "database"

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))


class RedisProbe:
    name = "redis"

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def ping(self) -> None:
        await self._client.ping()
