from __future__ import annotations

import json
import logging
import os
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_client: Redis | None = None


def cache_enabled() -> bool:
    return os.getenv("REDIS_ENABLED", "false").lower() in {"1", "true", "yes"}


def student_cache_key(student_card_number: str) -> str:
    return f"student:card:{student_card_number}"


def _redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DATABASE", "0")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _client


async def get_cached_student(student_card_number: str) -> dict[str, Any] | None:
    """Return a cached student, falling back silently when Redis is unavailable."""
    if not cache_enabled():
        return None
    try:
        value = await _redis().get(student_cache_key(student_card_number))
        cached = json.loads(value) if value is not None else None
        return cached if isinstance(cached, dict) else None
    except (RedisError, ValueError, TypeError):
        logger.warning("Could not read student cache", exc_info=True)
        return None


async def cache_student(student: dict[str, Any]) -> None:
    """Cache only the student representation, without related domain objects."""
    student_card_number = student.get("student_card_number")
    if not cache_enabled() or not student_card_number:
        return
    try:
        ttl = max(1, int(os.getenv("STUDENT_CACHE_TTL_SECONDS", "86400")))
        await _redis().set(
            student_cache_key(str(student_card_number)),
            json.dumps(student, ensure_ascii=False),
            ex=ttl,
        )
    except (RedisError, ValueError, TypeError):
        logger.warning("Could not update student cache", exc_info=True)


async def invalidate_student(student_card_number: str | None) -> None:
    if not cache_enabled() or not student_card_number:
        return
    try:
        await _redis().delete(student_cache_key(student_card_number))
    except RedisError:
        logger.warning("Could not invalidate student cache", exc_info=True)


async def close_cache() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
