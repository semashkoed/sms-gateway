"""Бинарный протокол поверх TCP: 4 байта длины (big-endian) + JSON.

Тот же принцип, что в SMPP: поток TCP не знает границ сообщений,
поэтому каждый кадр начинается с длины.
"""

import asyncio
import json
import struct

HEADER = struct.Struct("!I")
MAX_FRAME = 64 * 1024


class ProtocolError(Exception):
    pass


def encode_frame(obj: dict) -> bytes:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return HEADER.pack(len(payload)) + payload


async def read_frame(reader: asyncio.StreamReader) -> dict | None:
    """Читает один кадр. None — клиент штатно закрыл соединение."""
    try:
        header = await reader.readexactly(HEADER.size)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            return None
        raise ProtocolError("truncated header") from exc

    (length,) = HEADER.unpack(header)
    if length > MAX_FRAME:
        raise ProtocolError(f"frame too large: {length}")

    try:
        payload = await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise ProtocolError("truncated payload") from exc

    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise ProtocolError("invalid json") from exc
    if not isinstance(data, dict):
        raise ProtocolError("frame must be a json object")
    return data
