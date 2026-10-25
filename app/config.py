import os
from dataclasses import dataclass


def _parse_operators(raw: str) -> dict[str, str]:
    """'mts=http://a:9000,megafon=http://b:9000' -> {'mts': 'http://a:9000', ...}"""
    result: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in raw.split(","))):
        name, _, url = item.partition("=")
        if not name or not url:
            raise ValueError(f"Некорректный элемент OPERATORS: {item!r}")
        result[name.strip()] = url.strip().rstrip("/")
    return result


def _parse_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    tcp_host: str
    tcp_port: int
    pg_dsn: str  # пусто -> хранилище в памяти
    redis_url: str  # пусто -> rate limit в памяти
    pg_batch: bool  # пакетная запись статусов (см. BatchingPgStorage)
    routes_file: str
    operators: dict[str, str]
    workers: int
    queue_size: int
    retries_per_operator: int
    rate_limit: int
    rate_window: int
    max_segments: int
    stop_words: list[str]
    blacklist: list[str]
    translit_long: bool


def load_settings() -> Settings:
    env = os.environ.get
    return Settings(
        tcp_host=env("TCP_HOST", "0.0.0.0"),
        tcp_port=int(env("TCP_PORT", "9100")),
        pg_dsn=env("PG_DSN", ""),
        redis_url=env("REDIS_URL", ""),
        pg_batch=env("PG_BATCH", "1") == "1",
        routes_file=env("ROUTES_FILE", "config/routes.json"),
        operators=_parse_operators(
            env(
                "OPERATORS",
                "mts=http://127.0.0.1:9001,megafon=http://127.0.0.1:9002,tele2=http://127.0.0.1:9003",
            )
        ),
        workers=int(env("WORKERS", "64")),
        queue_size=int(env("QUEUE_SIZE", "50000")),
        retries_per_operator=int(env("RETRIES_PER_OPERATOR", "2")),
        rate_limit=int(env("RATE_LIMIT", "100")),
        rate_window=int(env("RATE_WINDOW", "1")),
        max_segments=int(env("MAX_SEGMENTS", "6")),
        stop_words=_parse_list(env("STOP_WORDS", "казино,ставки,кредит без справок")),
        blacklist=_parse_list(env("BLACKLIST", "+79990000000")),
        translit_long=env("TRANSLIT_LONG", "1") == "1",
    )
