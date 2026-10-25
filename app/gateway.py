"""Ядро шлюза: приём -> конвейер -> очередь -> воркеры -> операторы с fallback."""

import asyncio
import logging

from .models import Message, Status
from .operators import Operator, OperatorError
from .pipeline import Stage
from .router import Router
from .storage import Storage

log = logging.getLogger("gateway")


class Gateway:
    def __init__(
        self,
        stages: list[Stage],
        router: Router,
        operators: dict[str, Operator],
        storage: Storage,
        workers: int = 64,
        queue_size: int = 50_000,
        retries_per_operator: int = 2,
        retry_backoff: float = 0.05,
    ) -> None:
        self._stages = stages
        self._router = router
        self._operators = operators
        self._storage = storage
        self._workers_count = workers
        self._retries = retries_per_operator
        self._backoff = retry_backoff
        self.queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=queue_size)
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._worker(), name=f"worker-{i}") for i in range(self._workers_count)
        ]
        log.info("gateway started: %d workers", self._workers_count)

    async def stop(self, drain_timeout: float = 5.0) -> None:
        # Даём воркерам дослать то, что уже в очереди
        try:
            await asyncio.wait_for(self.queue.join(), drain_timeout)
        except TimeoutError:
            log.warning("stop: %d messages left in queue", self.queue.qsize())
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def submit(self, sender: str, recipient: str, text: str) -> Message:
        msg = Message(sender=sender, recipient=recipient, text=text)
        for stage in self._stages:
            reason = await stage.process(msg)
            if reason:
                msg.status, msg.reason = Status.REJECTED, reason
                await self._storage.save(msg)
                return msg

        await self._storage.save(msg)
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:
            # Backpressure: лучше честно отказать, чем копить бесконечно
            msg.status, msg.reason = Status.REJECTED, "gateway overloaded"
            await self._storage.save(msg)
        return msg

    async def status(self, msg_id: str) -> Message | None:
        return await self._storage.get(msg_id)

    async def stats(self, minutes: int = 60) -> dict:
        return {"queue_size": self.queue.qsize(), "rows": await self._storage.stats(minutes)}

    async def _worker(self) -> None:
        while True:
            msg = await self.queue.get()
            try:
                await self._deliver(msg)
            except Exception:
                log.exception("delivery crashed for %s", msg.id)
                msg.status, msg.reason = Status.FAILED, "internal error"
                await self._storage.save(msg)
            finally:
                self.queue.task_done()

    async def _deliver(self, msg: Message) -> None:
        for name in self._router.resolve(msg.recipient):
            operator = self._operators.get(name)
            if operator is None:
                log.warning("route points to unknown operator %r", name)
                continue
            for attempt in range(self._retries):
                msg.attempts += 1
                try:
                    await operator.send(msg)
                except OperatorError as exc:
                    msg.reason = f"{name}: {exc}"
                    await asyncio.sleep(self._backoff * 2**attempt)
                    continue
                msg.status, msg.route, msg.reason = Status.SENT, name, None
                await self._storage.save(msg)
                return
        msg.status = Status.FAILED
        msg.reason = msg.reason or "no operators for route"
        await self._storage.save(msg)
