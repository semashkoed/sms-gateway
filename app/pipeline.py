"""Конвейер обработки: фильтры и модификаторы.

Каждый этап получает сообщение и либо меняет его (модификатор),
либо возвращает причину отказа (фильтр). Порядок этапов задаётся в build_pipeline.
"""

import re
from typing import Protocol

from .config import Settings
from .models import Message
from .ratelimit import RateLimiter
from .sms import encoding_and_segments, has_cyrillic, normalize_phone, transliterate


class Stage(Protocol):
    name: str

    async def process(self, msg: Message) -> str | None:
        """None — продолжаем, строка — причина отказа."""
        ...


class NormalizeRecipient:
    name = "normalize_recipient"

    async def process(self, msg: Message) -> str | None:
        number = normalize_phone(msg.recipient)
        if number is None:
            return "invalid recipient number"
        msg.recipient = number
        return None


class Blacklist:
    name = "blacklist"

    def __init__(self, numbers: list[str]) -> None:
        self._numbers = {n for n in (normalize_phone(x) for x in numbers) if n}

    async def process(self, msg: Message) -> str | None:
        return "recipient is blacklisted" if msg.recipient in self._numbers else None


class StopWords:
    name = "stop_words"

    def __init__(self, words: list[str]) -> None:
        self._pattern = (
            re.compile("|".join(rf"\b{re.escape(w)}\b" for w in words), re.IGNORECASE) if words else None
        )

    async def process(self, msg: Message) -> str | None:
        if self._pattern and (m := self._pattern.search(msg.text)):
            return f"stop word: {m.group(0).lower()}"
        return None


class SenderRateLimit:
    name = "rate_limit"

    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def process(self, msg: Message) -> str | None:
        return None if await self._limiter.hit(msg.sender) else "rate limit exceeded"


class TransliterateLong:
    """Длинную кириллицу переводим в латиницу: UCS-2 даёт 70 симв./SMS, GSM-7 — 160.
    Абонент платит за каждую часть, так что это реальная экономия."""

    name = "transliterate"

    async def process(self, msg: Message) -> str | None:
        if not has_cyrillic(msg.text):
            return None
        segments = encoding_and_segments(msg.text)[1]
        if segments > 1:
            candidate = transliterate(msg.text)
            # Применяем, только если реально экономим (эмодзи, например, оставят UCS-2)
            if encoding_and_segments(candidate)[1] < segments:
                msg.text = candidate
        return None


class SegmentLimit:
    name = "segment_limit"

    def __init__(self, max_segments: int) -> None:
        self._max = max_segments

    async def process(self, msg: Message) -> str | None:
        msg.encoding, msg.segments = encoding_and_segments(msg.text)
        if msg.segments > self._max:
            return f"too long: {msg.segments} segments (max {self._max})"
        return None


def build_pipeline(settings: Settings, limiter: RateLimiter) -> list[Stage]:
    stages: list[Stage] = [
        NormalizeRecipient(),
        Blacklist(settings.blacklist),
        StopWords(settings.stop_words),  # проверяем исходный текст, до транслитерации
        SenderRateLimit(limiter),
    ]
    if settings.translit_long:
        stages.append(TransliterateLong())
    stages.append(SegmentLimit(settings.max_segments))
    return stages
