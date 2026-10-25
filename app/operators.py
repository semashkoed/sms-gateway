"""Клиенты операторов связи. В проекте — HTTP; в реальности тут был бы SMPP.

Используется aiohttp, а не httpx: на 128 параллельных запросах httpx тратил
~6.6 мс CPU на запрос против ~0.2 мс у aiohttp (замер в README).
"""

from typing import Protocol

import aiohttp

from .models import Message


class OperatorError(Exception):
    pass


class Operator(Protocol):
    name: str

    async def send(self, msg: Message) -> None:
        """Ничего не возвращает при успехе, бросает OperatorError при ошибке."""
        ...


class HttpOperator:
    def __init__(self, name: str, url: str, session: aiohttp.ClientSession, timeout: float = 2.0):
        self.name = name
        self._url = f"{url}/submit"
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def send(self, msg: Message) -> None:
        payload = {"id": msg.id, "from": msg.sender, "to": msg.recipient, "text": msg.text}
        try:
            async with self._session.post(self._url, json=payload, timeout=self._timeout) as resp:
                await resp.read()
                if resp.status != 200:
                    raise OperatorError(f"HTTP {resp.status}")
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise OperatorError(type(exc).__name__) from exc
