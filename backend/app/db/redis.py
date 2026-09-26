"""Async Redis client construction."""

from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    """Create a pooled async Redis client. No connection is opened until first command."""
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return client
