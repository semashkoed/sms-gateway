from app.models import Message
from app.pipeline import (
    Blacklist,
    NormalizeRecipient,
    SegmentLimit,
    SenderRateLimit,
    StopWords,
    TransliterateLong,
)
from app.ratelimit import InMemoryRateLimiter


def make(text="hello", recipient="+79131234567", sender="SHOP"):
    return Message(sender=sender, recipient=recipient, text=text)


async def test_normalize_rejects_garbage():
    assert await NormalizeRecipient().process(make(recipient="12")) == "invalid recipient number"


async def test_blacklist_matches_any_format():
    stage = Blacklist(["8 913 000-00-00"])
    assert await stage.process(make(recipient="+79130000000"))
    assert await stage.process(make(recipient="+79131111111")) is None


async def test_stop_words_whole_word_case_insensitive():
    stage = StopWords(["казино"])
    assert await stage.process(make(text="Лучшее КАЗИНО города")) == "stop word: казино"
    assert await stage.process(make(text="казиноморе")) is None


async def test_rate_limit():
    stage = SenderRateLimit(InMemoryRateLimiter(limit=3, window_sec=60))
    results = [await stage.process(make()) for _ in range(5)]
    assert results[:3] == [None, None, None]
    assert results[3:] == ["rate limit exceeded"] * 2
    assert await stage.process(make(sender="OTHER")) is None  # лимит — на отправителя


async def test_translit_only_for_long_cyrillic():
    short = make(text="Код: 1234")
    await TransliterateLong().process(short)
    assert short.text == "Код: 1234"

    long = make(text="Здравствуйте! " * 6)
    await TransliterateLong().process(long)
    assert long.text.startswith("Zdravstvuyte!")


async def test_translit_handles_typography_and_skips_emoji():
    order = make(text="Заказ №1532 «собран» — ожидайте курьера завтра с 10 до 14 часов, спасибо!")
    await TransliterateLong().process(order)
    assert order.text.startswith('Zakaz N1532 "sobran" -')
    assert (await SegmentLimit(6).process(order), order.encoding, order.segments) == (None, "gsm7", 1)

    emoji = make(text="Привет 😀 " * 10)
    await TransliterateLong().process(emoji)
    assert emoji.text.startswith("Привет")  # транслит не помог бы — текст не трогаем


async def test_segment_limit_sets_encoding():
    msg = make(text="я" * 71)
    assert await SegmentLimit(max_segments=6).process(msg) is None
    assert (msg.encoding, msg.segments) == ("ucs2", 2)
    assert await SegmentLimit(max_segments=1).process(make(text="a" * 200))
