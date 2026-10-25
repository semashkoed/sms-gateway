"""Интеграционные тесты с настоящим PostgreSQL.

Запускаются, только если задан TEST_PG_DSN (в CI поднимается сервис postgres):
  TEST_PG_DSN=postgresql://sms:sms@localhost:5432/sms pytest tests/test_pg_storage.py
"""

import os

import asyncpg
import pytest

from app.models import Message, Status
from app.storage import BatchingPgStorage, PgStorage

DSN = os.environ.get("TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_PG_DSN не задан")


@pytest.fixture
async def pool():
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4)
    await PgStorage(pool).init_schema()
    await pool.execute("TRUNCATE messages")
    yield pool
    await pool.close()


async def test_upsert_and_get(pool):
    storage = PgStorage(pool)
    msg = Message(sender="SHOP", recipient="+79131234567", text="hi")
    await storage.save(msg)
    msg.status, msg.route, msg.attempts = Status.SENT, "mts", 2
    await storage.save(msg)

    loaded = await storage.get(msg.id)
    assert (loaded.status, loaded.route, loaded.attempts) == (Status.SENT, "mts", 2)
    assert await pool.fetchval("SELECT count(*) FROM messages") == 1


async def test_batching_collapses_updates_and_flushes_on_stop(pool):
    storage = BatchingPgStorage(pool, flush_interval=10)  # сами вызовем stop()
    await storage.start()
    msgs = [Message(sender="S", recipient=f"+7913000{i:04d}", text="t") for i in range(500)]
    for m in msgs:
        await storage.save(m)
        m.status = Status.SENT
        await storage.save(m)  # вторая версия того же сообщения

    assert (await storage.get(msgs[0].id)).status == Status.SENT  # читается из буфера
    assert await pool.fetchval("SELECT count(*) FROM messages") == 0  # в базе ещё пусто

    await storage.stop()
    rows = await pool.fetch("SELECT status, count(*) FROM messages GROUP BY 1")
    assert [tuple(r) for r in rows] == [("sent", 500)]


async def test_stats_sql(pool):
    storage = PgStorage(pool)
    for route, status in [("mts", Status.SENT), ("mts", Status.SENT), (None, Status.REJECTED)]:
        m = Message(sender="S", recipient="+79131234567", text="t", route=route, status=status)
        await storage.save(m)
    stats = {(r["route"], r["status"]): r["messages"] for r in await storage.stats(60)}
    assert stats == {("mts", "sent"): 2, ("-", "rejected"): 1}
