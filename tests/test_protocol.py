import asyncio

import pytest

from app.protocol import HEADER, ProtocolError, encode_frame, read_frame


def reader_with(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


async def test_roundtrip_several_frames():
    data = encode_frame({"cmd": "ping", "seq": 1}) + encode_frame({"text": "привет"})
    reader = reader_with(data)
    assert await read_frame(reader) == {"cmd": "ping", "seq": 1}
    assert await read_frame(reader) == {"text": "привет"}
    assert await read_frame(reader) is None  # чистый EOF


async def test_truncated_payload():
    frame = encode_frame({"a": 1})
    with pytest.raises(ProtocolError):
        await read_frame(reader_with(frame[:-2]))


async def test_too_large_frame():
    with pytest.raises(ProtocolError):
        await read_frame(reader_with(HEADER.pack(10_000_000)))


async def test_invalid_json():
    with pytest.raises(ProtocolError):
        await read_frame(reader_with(HEADER.pack(3) + b"{{{"))
