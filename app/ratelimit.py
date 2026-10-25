"""Rate limit по отправителю: фиксированное окно (INCR + EXPIRE в Redis)."""

import time
from collections import defaultdict
from typing import Protocol

from redis.asyncio import Redis


class RateLimiter(Protocol):
    async def hit(self, key: str) -> bool:
        """True — запрос в пределах лимита, False — лимит превышен."""
        ...


class RedisRateLimiter:
    def __init__(self, redis: Redis, limit: int, window_sec: int) -> None:
        self._redis = redis
        self._limit = limit
        self._window = window_sec

    async def hit(self, key: str) -> bool:
        bucket = int(time.time() // self._window)
        redis_key = f"rl:{key}:{bucket}"
        # Атомарно: MULTI / INCR / EXPIRE / EXEC — один round-trip до Redis
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, self._window * 2)
            count, _ = await pipe.execute()
        return count <= self._limit


class InMemoryRateLimiter:
    """Для тестов и запуска без Redis. Работает только в рамках одного процесса."""

    def __init__(self, limit: int, window_sec: int) -> None:
        self._limit = limit
        self._window = window_sec
        self._counters: dict[tuple[str, int], int] = defaultdict(int)

    async def hit(self, key: str) -> bool:
        bucket = int(time.time() // self._window)
        self._counters[(key, bucket)] += 1
        if len(self._counters) > 100_000:  # не даём словарю расти бесконечно
            self._counters = defaultdict(int, {k: v for k, v in self._counters.items() if k[1] == bucket})
        return self._counters[(key, bucket)] <= self._limit
