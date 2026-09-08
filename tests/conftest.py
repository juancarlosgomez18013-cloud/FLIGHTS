from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from cheapflights.config import load_config
from cheapflights.history import History
from cheapflights.search import RouteResult

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def config():
    return load_config(ROOT / "config.yaml")


@pytest.fixture
def history(tmp_path):
    return History(path=tmp_path / "history.json")


def make_result(origin="BGA", destination="BOG", prices=None, start=None):
    start = start or (date.today() + timedelta(days=1))
    prices = prices or [200_000, 150_000, 180_000]
    cal = {(start + timedelta(days=i)).isoformat(): float(p) for i, p in enumerate(prices)}
    return RouteResult(origin=origin, destination=destination, calendar=cal, currency="COP")


@pytest.fixture
def make_route_result():
    return make_result
