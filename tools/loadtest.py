"""Нагрузочный тест TCP-интерфейса шлюза.

Пример: python tools/loadtest.py --connections 100 --total 20000
"""

import argparse
import asyncio
import json
import random
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.protocol import encode_frame, read_frame  # noqa: E402

PREFIXES = ["913", "923", "902", "950", "999"]


def random_message(i: int) -> dict:
    return {
        "cmd": "submit",
        "seq": i,
        "sender": f"SENDER{random.randint(1, 2000)}",  # много отправителей, чтобы не упереться в rate limit
        "recipient": f"8{random.choice(PREFIXES)}{random.randint(0, 9_999_999):07d}",
        "text": random.choice(["Ваш код: 4821", "Order shipped", "Заказ №1532 передан в доставку"]),
    }


async def client(host: str, port: int, count: int, latencies: list[float], statuses: Counter):
    reader, writer = await asyncio.open_connection(host, port)
    for i in range(count):
        started = time.perf_counter()
        writer.write(encode_frame(random_message(i)))
        await writer.drain()
        resp = await read_frame(reader)
        latencies.append(time.perf_counter() - started)
        statuses[resp.get("status") or resp.get("reason") or resp.get("error")] += 1
    writer.close()
    await writer.wait_closed()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9100)
    p.add_argument("--connections", type=int, default=50)
    p.add_argument("--total", type=int, default=10_000)
    p.add_argument(
        "--stats-url",
        default="http://127.0.0.1:8000/stats",
        help="откуда брать размер очереди; пустая строка — не ждать доставки",
    )
    args = p.parse_args()

    per_conn = args.total // args.connections
    latencies: list[float] = []
    statuses: Counter = Counter()

    started = time.perf_counter()
    await asyncio.gather(
        *(client(args.host, args.port, per_conn, latencies, statuses) for _ in range(args.connections))
    )
    elapsed = time.perf_counter() - started

    latencies.sort()
    n = len(latencies)
    print(f"messages:          {n}")
    print(f"connections:       {args.connections}")
    print(f"accept elapsed:    {elapsed:.2f} s")
    print(f"accept throughput: {n / elapsed:,.0f} msg/s")
    print(f"accept p50:        {latencies[n // 2] * 1000:.1f} ms")
    print(f"accept p99:        {latencies[int(n * 0.99)] * 1000:.1f} ms")
    print(f"statuses:          {dict(statuses)}")

    if args.stats_url:
        # Приём быстрее доставки — сообщения копятся в очереди. Ждём, пока она опустеет.
        # Опрос чужого процесса по HTTP — Event тут неприменим
        while await asyncio.to_thread(queue_size, args.stats_url) > 0:  # noqa: ASYNC110
            await asyncio.sleep(0.2)
        total = time.perf_counter() - started
        print(f"end-to-end:        {total:.2f} s, {n / total:,.0f} msg/s delivered (queue drained)")


def queue_size(stats_url: str) -> int:
    with urllib.request.urlopen(stats_url, timeout=5) as resp:
        return json.load(resp)["queue_size"]


if __name__ == "__main__":
    asyncio.run(main())
