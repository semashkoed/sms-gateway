"""Хранилище статусов сообщений: PostgreSQL (asyncpg) или память."""

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Protocol

import asyncpg

from .models import Message, Status

log = logging.getLogger("storage")

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "migrations" / "001_init.sql"

UPSERT_SQL = """
INSERT INTO messages (id, sender, recipient, text, status, reason, route,
                      attempts, encoding, segments, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, to_timestamp($11))
ON CONFLICT (id) DO UPDATE SET
    status     = EXCLUDED.status,
    reason     = EXCLUDED.reason,
    route      = EXCLUDED.route,
    attempts   = EXCLUDED.attempts,
    updated_at = now()
"""

STATS_SQL = """
SELECT coalesce(route, '-')               AS route,
       status,
       count(*)                           AS messages,
       sum(segments)                      AS segments,
       round(avg(attempts)::numeric, 2)   AS avg_attempts
FROM messages
WHERE created_at > now() - make_interval(mins => $1)
GROUP BY 1, 2
ORDER BY 1, 2
"""


class Storage(Protocol):
    async def save(self, msg: Message) -> None: ...
    async def get(self, msg_id: str) -> Message | None: ...
    async def stats(self, minutes: int) -> list[dict]: ...


class PgStorage:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

    @staticmethod
    def _row(msg: Message) -> tuple:
        return (
            msg.id, msg.sender, msg.recipient, msg.text, msg.status.value, msg.reason,
            msg.route, msg.attempts, msg.encoding, msg.segments, msg.created_at,
        )  # fmt: skip

    async def save(self, msg: Message) -> None:
        await self._pool.execute(UPSERT_SQL, *self._row(msg))

    async def get(self, msg_id: str) -> Message | None:
        row = await self._pool.fetchrow(
            "SELECT *, extract(epoch FROM created_at) AS ts FROM messages WHERE id = $1",
            msg_id,
        )
        if row is None:
            return None
        return Message(
            id=row["id"], sender=row["sender"], recipient=row["recipient"], text=row["text"],
            status=Status(row["status"]), reason=row["reason"], route=row["route"],
            attempts=row["attempts"], encoding=row["encoding"], segments=row["segments"],
            created_at=float(row["ts"]),
        )  # fmt: skip

    async def stats(self, minutes: int) -> list[dict]:
        rows = await self._pool.fetch(STATS_SQL, minutes)
        return [{**dict(r), "avg_attempts": float(r["avg_attempts"] or 0)} for r in rows]


class BatchingPgStorage(PgStorage):
    """Пакетная запись: save() кладёт сообщение в буфер, фоновая задача раз в
    flush_interval пишет весь буфер одной транзакцией через executemany.

    Почему так: один INSERT с коммитом = один fsync на диске PostgreSQL.
    Пачка из тысячи строк в одной транзакции — тоже один fsync.

    Цена: при падении процесса теряются статусы за последние flush_interval секунд.
    Если сообщение успело и принять, и отправиться в пределах одного интервала,
    в базу уйдёт одна строка с итоговым статусом вместо двух запросов.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        flush_interval: float = 0.05,
        max_batch: int = 2000,
        max_pending: int = 100_000,
    ) -> None:
        super().__init__(pool)
        self._interval = flush_interval
        self._max_batch = max_batch
        self._max_pending = max_pending
        self._pending: dict[str, Message] = {}
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._flusher(), name="pg-flusher")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self._flush()  # дописываем остаток

    async def save(self, msg: Message) -> None:
        self._pending[msg.id] = msg  # ссылка на объект: при сбросе пишется самое свежее состояние
        if len(self._pending) >= self._max_batch:
            self._wakeup.set()
        if len(self._pending) >= self._max_pending:
            # База не успевает — тормозим отправителей вместо роста памяти
            await self._flush()

    async def get(self, msg_id: str) -> Message | None:
        if (msg := self._pending.get(msg_id)) is not None:
            return msg
        return await super().get(msg_id)

    async def _flusher(self) -> None:
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), self._interval)
            self._wakeup.clear()
            try:
                await self._flush()
            except Exception:
                log.exception("flush failed, %d messages kept in buffer", len(self._pending))
                await asyncio.sleep(1)

    async def _flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, {}
        try:
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.executemany(UPSERT_SQL, [self._row(m) for m in batch.values()])
        except Exception:
            # Возвращаем в буфер, не затирая более свежие версии
            for msg_id, msg in batch.items():
                self._pending.setdefault(msg_id, msg)
            raise


class InMemoryStorage:
    def __init__(self) -> None:
        self._data: dict[str, Message] = {}

    async def save(self, msg: Message) -> None:
        self._data[msg.id] = msg

    async def get(self, msg_id: str) -> Message | None:
        return self._data.get(msg_id)

    async def stats(self, minutes: int) -> list[dict]:
        groups: dict[tuple[str, str], list[Message]] = {}
        for m in self._data.values():
            groups.setdefault((m.route or "-", m.status.value), []).append(m)
        return [
            {
                "route": route,
                "status": status,
                "messages": len(ms),
                "segments": sum(m.segments for m in ms),
                "avg_attempts": round(sum(m.attempts for m in ms) / len(ms), 2),
            }
            for (route, status), ms in sorted(groups.items())
        ]
