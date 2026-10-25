"""Точка входа: HTTP API (FastAPI) и TCP-сервер в одном event loop.

Запуск: uvicorn app.main:app --port 8000
"""

import logging
import os
from contextlib import asynccontextmanager

import aiohttp
import asyncpg
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from .config import load_settings
from .gateway import Gateway
from .operators import HttpOperator
from .pipeline import build_pipeline
from .ratelimit import InMemoryRateLimiter, RedisRateLimiter
from .router import Router
from .storage import BatchingPgStorage, InMemoryStorage, PgStorage
from .tcp_server import TcpServer

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = load_settings()

    pool = None
    batching: BatchingPgStorage | None = None
    if s.pg_dsn:
        pool = await asyncpg.create_pool(s.pg_dsn, min_size=2, max_size=20)
        if s.pg_batch:
            storage = batching = BatchingPgStorage(pool)
            await batching.start()
        else:
            storage = PgStorage(pool)
        await storage.init_schema()
    else:
        log.warning("PG_DSN не задан — статусы хранятся в памяти")
        storage = InMemoryStorage()

    redis = None
    if s.redis_url:
        redis = Redis.from_url(s.redis_url)
        limiter = RedisRateLimiter(redis, s.rate_limit, s.rate_window)
    else:
        log.warning("REDIS_URL не задан — rate limit в памяти")
        limiter = InMemoryRateLimiter(s.rate_limit, s.rate_window)

    # Одна сессия на всё приложение: пул keep-alive соединений к операторам
    http = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=200, limit_per_host=100))
    operators = {name: HttpOperator(name, url, http) for name, url in s.operators.items()}

    gateway = Gateway(
        stages=build_pipeline(s, limiter),
        router=Router.from_file(s.routes_file),
        operators=operators,
        storage=storage,
        workers=s.workers,
        queue_size=s.queue_size,
        retries_per_operator=s.retries_per_operator,
    )
    await gateway.start()
    tcp = TcpServer(gateway, s.tcp_host, s.tcp_port)
    await tcp.start()

    app.state.gateway = gateway
    try:
        yield
    finally:
        await tcp.stop()
        await gateway.stop()
        if batching is not None:
            await batching.stop()
        await http.close()
        if redis is not None:
            await redis.aclose()
        if pool is not None:
            await pool.close()


app = FastAPI(title="SMS Gateway", version="1.0.0", lifespan=lifespan)


class SubmitRequest(BaseModel):
    sender: str = Field(min_length=1, max_length=15, examples=["SHOP"])
    recipient: str = Field(min_length=5, max_length=20, examples=["8 (913) 123-45-67"])
    text: str = Field(min_length=1, max_length=1600, examples=["Ваш код: 1234"])


def _gw(request: Request) -> Gateway:
    return request.app.state.gateway


@app.post("/sms")
async def submit_sms(body: SubmitRequest, request: Request) -> dict:
    msg = await _gw(request).submit(body.sender, body.recipient, body.text)
    return msg.public()


@app.get("/sms/{msg_id}")
async def get_sms(msg_id: str, request: Request) -> dict:
    msg = await _gw(request).status(msg_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="message not found")
    return msg.public()


@app.get("/stats")
async def stats(request: Request, minutes: int = 60) -> dict:
    return await _gw(request).stats(minutes)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
