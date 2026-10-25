import pytest

from app.sms import encoding_and_segments, normalize_phone, transliterate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("89131234567", "+79131234567"),
        ("+7 (913) 123-45-67", "+79131234567"),
        ("9131234567", "+79131234567"),
        ("+375291234567", "+375291234567"),
        ("12345", None),
        ("abc", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_gsm7_single_and_multipart():
    assert encoding_and_segments("a" * 160) == ("gsm7", 1)
    assert encoding_and_segments("a" * 161) == ("gsm7", 2)
    assert encoding_and_segments("a" * 306) == ("gsm7", 2)
    assert encoding_and_segments("a" * 307) == ("gsm7", 3)


def test_gsm7_extended_chars_count_double():
    assert encoding_and_segments("€" * 80) == ("gsm7", 1)
    assert encoding_and_segments("€" * 81) == ("gsm7", 2)


def test_ucs2():
    assert encoding_and_segments("я" * 70) == ("ucs2", 1)
    assert encoding_and_segments("я" * 71) == ("ucs2", 2)
    assert encoding_and_segments("😀" * 35) == ("ucs2", 1)  # эмодзи = 2 позиции


def test_transliterate_keeps_case_and_non_cyrillic():
    assert transliterate("Привет, Щука! 123") == "Privet, Shchuka! 123"
