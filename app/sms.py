"""SMS-специфика: нормализация номера, кодировка, сегменты, транслитерация."""

import math
import re

# Базовый алфавит GSM 03.38: такие символы занимают 7 бит
GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
# Расширенная таблица: символ кодируется через escape, т.е. занимает 2 позиции
GSM7_EXTENDED = set("^{}\\[~]|€\f")

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # типографские символы вне GSM-7: без замены сообщение осталось бы в UCS-2
    "№": "N", "«": '"', "»": '"', "—": "-", "–": "-", "…": "...", "’": "'",
}  # fmt: skip

_NON_DIGITS = re.compile(r"\D")
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)


def normalize_phone(raw: str) -> str | None:
    """Приводит номер к E.164 (+7XXXXXXXXXX). Возвращает None, если номер невалиден."""
    digits = _NON_DIGITS.sub("", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    if not 11 <= len(digits) <= 15:
        return None
    return "+" + digits


def is_gsm7(text: str) -> bool:
    return all(ch in GSM7_BASIC or ch in GSM7_EXTENDED for ch in text)


def encoding_and_segments(text: str) -> tuple[str, int]:
    """Кодировка и число SMS-частей.

    GSM-7: 160 символов в одной SMS, 153 в каждой части составной.
    UCS-2 (кириллица, эмодзи): 70 и 67 соответственно.
    """
    if is_gsm7(text):
        length = sum(2 if ch in GSM7_EXTENDED else 1 for ch in text)
        single, multi, encoding = 160, 153, "gsm7"
    else:
        length = len(text.encode("utf-16-le")) // 2  # эмодзи занимают 2 позиции
        single, multi, encoding = 70, 67, "ucs2"
    if length <= single:
        return encoding, 1
    return encoding, math.ceil(length / multi)


def has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC.search(text))


def transliterate(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        if low in TRANSLIT:
            lat = TRANSLIT[low]
            out.append(lat.capitalize() if ch != low else lat)
        else:
            out.append(ch)
    return "".join(out)
