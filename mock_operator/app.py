"""Заглушка оператора связи: случайная задержка и доля ошибок задаются через env.

Запуск: OPERATOR_NAME=mts FAIL_RATE=0.1 uvicorn mock_operator.app:app --port 9001
"""

import asyncio
import os
import random

from fastapi import FastAPI, HTTPException

NAME = os.environ.get("OPERATOR_NAME", "mock")
LATENCY_MS = float(os.environ.get("LATENCY_MS", "30"))
FAIL_RATE = float(os.environ.get("FAIL_RATE", "0"))

app = FastAPI(title=f"Mock operator: {NAME}")
counters = {"accepted": 0, "failed": 0}


@app.post("/submit")
async def submit(payload: dict) -> dict:
    await asyncio.sleep(random.uniform(0.5, 1.5) * LATENCY_MS / 1000)
    if random.random() < FAIL_RATE:
        counters["failed"] += 1
        raise HTTPException(status_code=503, detail="operator busy")
    counters["accepted"] += 1
    return {"operator": NAME, "id": payload.get("id"), "accepted": True}


@app.get("/health")
async def health() -> dict:
    return {"operator": NAME, **counters}
