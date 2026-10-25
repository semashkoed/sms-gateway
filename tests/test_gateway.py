"""Сквозной тест шлюза без сети: фейковые операторы и хранилище в памяти."""

import asyncio

import pytest

from app.gateway import Gateway
from app.models import Message, Status
from app.operators import OperatorError
from app.pipeline import NormalizeRecipient, StopWords
from app.protocol import encode_frame, read_frame
from app.router import Route, Router
from app.storage import InMemoryStorage
from app.tcp_server import TcpServer


class FakeOperator:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.received: list[Message] = []

    async def send(self, msg: Message) -> None:
        if self.fail:
            raise OperatorError("down")
        self.received.append(msg)


@pytest.fixture
async def setup():
    mts, megafon = FakeOperator("mts", fail=True), FakeOperator("megafon")
    gw = Gateway(
        stages=[NormalizeRecipient(), StopWords(["казино"])],
        router=Router([Route("+7913", ["mts", "megafon"])], default=["mts"]),
        operators={"mts": mts, "megafon": megafon},
        storage=InMemoryStorage(),
        workers=4,
        retry_backoff=0,
    )
    await gw.start()
    yield gw, mts, megafon
    await gw.stop()


async def test_fallback_to_second_operator(setup):
    gw, _, megafon = setup
    msg = await gw.submit("SHOP", "89131234567", "Ваш заказ готов")
    assert msg.status == Status.ACCEPTED
    await gw.queue.join()

    stored = await gw.status(msg.id)
    assert stored.status == Status.SENT
    assert stored.route == "megafon"
    assert stored.attempts == 3  # 2 попытки в mts + 1 в megafon
    assert megafon.received[0].recipient == "+79131234567"


async def test_all_operators_fail(setup):
    gw, *_ = setup
    msg = await gw.submit("SHOP", "+79001234567", "hi")  # default -> только mts (падает)
    await gw.queue.join()
    stored = await gw.status(msg.id)
    assert stored.status == Status.FAILED
    assert stored.reason == "mts: down"


async def test_rejected_by_filter_never_queued(setup):
    gw, *_ = setup
    msg = await gw.submit("SHOP", "+79131234567", "лучшее казино")
    assert msg.status == Status.REJECTED
    assert gw.queue.qsize() == 0


async def test_tcp_server_end_to_end(setup):
    gw, *_ = setup
    server = TcpServer(gw, "127.0.0.1", 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(encode_frame({"cmd": "ping", "seq": 1}))
        writer.write(
            encode_frame({"cmd": "submit", "seq": 2, "sender": "S", "recipient": "89131234567",
                          "text": "hi"})
        )  # fmt: skip
        writer.write(encode_frame({"cmd": "submit", "seq": 3, "sender": "S"}))
        await writer.drain()

        assert await read_frame(reader) == {"seq": 1, "cmd": "pong"}
        submitted = await read_frame(reader)
        assert submitted["seq"] == 2 and submitted["status"] == "accepted"
        assert (await read_frame(reader))["error"] == "missing field recipient"

        await gw.queue.join()
        writer.write(encode_frame({"cmd": "status", "seq": 4, "id": submitted["id"]}))
        await writer.drain()
        assert (await read_frame(reader))["status"] == "sent"
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()
