"""TCP-сервер для «быстрых» клиентов (аналог SMPP-подключения).

Команды:
  {"cmd": "ping", "seq": 1}
  {"cmd": "submit", "seq": 2, "sender": "SHOP", "recipient": "89131234567", "text": "..."}
  {"cmd": "status", "seq": 3, "id": "<message id>"}
"""

import asyncio
import contextlib
import logging

from .gateway import Gateway
from .protocol import ProtocolError, encode_frame, read_frame

log = logging.getLogger("tcp")


class TcpServer:
    def __init__(self, gateway: Gateway, host: str, port: int) -> None:
        self._gateway = gateway
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        log.info("tcp listening on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.debug("client connected: %s", peer)
        try:
            while True:
                try:
                    request = await read_frame(reader)
                except ProtocolError as exc:
                    writer.write(encode_frame({"error": str(exc)}))
                    await writer.drain()
                    break
                if request is None:
                    break
                writer.write(encode_frame(await self._dispatch(request)))
                await writer.drain()  # backpressure: ждём, если клиент не успевает читать
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            log.debug("client disconnected: %s", peer)

    async def _dispatch(self, req: dict) -> dict:
        seq = req.get("seq")
        cmd = req.get("cmd")
        if cmd == "ping":
            return {"seq": seq, "cmd": "pong"}
        if cmd == "submit":
            try:
                sender, recipient, text = str(req["sender"]), str(req["recipient"]), str(req["text"])
            except KeyError as exc:
                return {"seq": seq, "error": f"missing field {exc.args[0]}"}
            if not text:
                return {"seq": seq, "error": "empty text"}
            msg = await self._gateway.submit(sender, recipient, text)
            return {"seq": seq, "id": msg.id, "status": msg.status.value, "reason": msg.reason}
        if cmd == "status":
            msg = await self._gateway.status(str(req.get("id", "")))
            if msg is None:
                return {"seq": seq, "error": "not found"}
            return {"seq": seq, **msg.public()}
        return {"seq": seq, "error": f"unknown command {cmd!r}"}
