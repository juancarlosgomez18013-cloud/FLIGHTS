from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from cheapflights.config import Zone, load_config
from cheapflights.history import History
from cheapflights.search import RouteResult

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 9, 23)
NOW = datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc)  # 12:00 hora Colombia


@pytest.fixture
def config():
    return load_config(ROOT / "config.yaml")


@pytest.fixture
def history(tmp_path):
    return History(path=tmp_path / "history.json")


ZONE = Zone(
    name="Bogotá", emoji="🏙️", kind="domestic", origins=("BGA",), destinations=("BOG",),
    super_price=80_000, cheap_price=110_000, months_ahead=6,
)


def make_result(origin="BGA", destination="BOG", prices=None, start=None):
    start = start or (TODAY + timedelta(days=1))
    prices = prices or [200_000, 150_000, 180_000]
    cal = {(start + timedelta(days=i)).isoformat(): float(p) for i, p in enumerate(prices)}
    return RouteResult(origin=origin, destination=destination, calendar=cal, currency="COP")


def calendar(prices, start=None):
    start = start or (TODAY + timedelta(days=1))
    return {(start + timedelta(days=i)).isoformat(): float(p) for i, p in enumerate(prices)}


def runs(mins, start=NOW - timedelta(days=30), step_hours=24):
    return [
        {"seen_at": (start + timedelta(hours=i * step_hours)).isoformat(), "min_price": m, "min_date": "2026-10-01", "median_price": m}
        for i, m in enumerate(mins)
    ]
