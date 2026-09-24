from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from cheapflights.config import Zone, load_config
from cheapflights.history import History
from cheapflights.search import Fares, Route, RouteResult

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 9, 23)
NOW = datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc)  # 12:00 hora Colombia
NIGHTS = (2, 5)


@pytest.fixture
def config():
    return load_config(ROOT / "config.yaml")


@pytest.fixture
def history(tmp_path):
    return History(path=tmp_path / "history.json")


ZONE = Zone(
    name="Bogotá", emoji="🏙️", kind="domestic", origins=("BGA",), destinations=("BOG",),
    months_ahead=6, nights=NIGHTS, bags=0, super_price=80_000, cheap_price=110_000,
)


def route(origin="BGA", destination="BOG", nights=NIGHTS, bags=0) -> Route:
    return Route(origin, destination, nights, bags)


def fares(prices, start=None, nights=NIGHTS) -> Fares:
    """Un viaje por fecha de ida (con el mínimo de noches), un precio por día a partir de mañana."""
    start = start or (TODAY + timedelta(days=1))
    return {
        ((start + timedelta(days=i)).isoformat(), (start + timedelta(days=i + nights[0])).isoformat()): float(p)
        for i, p in enumerate(prices)
    }


def make_result(origin="BGA", destination="BOG", prices=None, start=None, nights=NIGHTS, bags=0):
    prices = prices or [200_000, 150_000, 180_000]
    r = route(origin, destination, nights, bags)
    return RouteResult(route=r, fares=fares(prices, start, nights), currency="COP")


def runs(mins, start=NOW - timedelta(days=30), step_hours=24):
    return [
        {
            "seen_at": (start + timedelta(hours=i * step_hours)).isoformat(),
            "min_price": m, "min_out": "2026-10-01", "min_back": "2026-10-03", "median_price": m,
        }
        for i, m in enumerate(mins)
    ]
