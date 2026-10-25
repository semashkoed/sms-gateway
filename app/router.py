"""Маршрутизация по префиксу номера (longest prefix match)."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Route:
    prefix: str
    operators: list[str]  # порядок = приоритет; следующие — запасные (fallback)


class Router:
    def __init__(self, routes: list[Route], default: list[str]) -> None:
        # Сортируем по длине префикса: первый совпавший — самый специфичный
        self._routes = sorted(routes, key=lambda r: len(r.prefix), reverse=True)
        self._default = default

    def resolve(self, number: str) -> list[str]:
        for route in self._routes:
            if number.startswith(route.prefix):
                return route.operators
        return self._default

    @classmethod
    def from_file(cls, path: str | Path) -> "Router":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        routes = [Route(r["prefix"], list(r["operators"])) for r in data["routes"]]
        return cls(routes, list(data.get("default", [])))
