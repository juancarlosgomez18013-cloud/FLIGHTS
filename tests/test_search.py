from datetime import date

import pytest

from cheapflights.search import (
    MAX_COMBOS_PER_REQUEST,
    RateLimited,
    Route,
    RouteResult,
    chunk_days,
    n_durations,
    search_routes,
    window_around,
)


def test_route_key_pair_and_other_bags():
    r = Route("BGA", "CTG", (2, 5), 0)
    assert r.key == "BGA-CTG/2-5n/0m" and r.pair == "BGA-CTG" and str(r) == r.key
    assert r.other_bags == Route("BGA", "CTG", (2, 5), 1) and r.other_bags.other_bags == r


def test_chunk_days_respects_google_cap():
    assert chunk_days((3, 3)) == 61  # una sola duración: el límite de días de Google
    assert chunk_days((2, 5)) == 45 and chunk_days((6, 14)) == 20 and chunk_days((6, 16)) == 16
    for nights in [(1, 1), (2, 5), (6, 14), (6, 16), (1, 30)]:
        assert 1 <= chunk_days(nights) and chunk_days(nights) * n_durations(nights) <= max(MAX_COMBOS_PER_REQUEST, n_durations(nights))


def test_window_around_fits_one_request_and_stays_in_range():
    start, end = date(2026, 10, 1), date(2026, 12, 31)
    lo, hi = window_around("2026-11-20", (2, 5), start, end)
    assert (hi - lo).days + 1 == 45 and lo <= date(2026, 11, 20) <= hi
    assert window_around("2026-10-02", (2, 5), start, end) == (start, date(2026, 11, 14))
    assert window_around("2026-12-30", (2, 5), start, end) == (date(2026, 11, 17), end)
    assert window_around("2026-10-05", (2, 5), start, date(2026, 10, 10)) == (start, date(2026, 10, 10))


def test_cheapest_prefers_lowest_price_then_earliest_trip():
    r = RouteResult(Route("BGA", "CTG", (2, 5)), {("2026-10-02", "2026-10-04"): 100.0, ("2026-10-01", "2026-10-03"): 100.0, ("2026-10-01", "2026-10-05"): 90.0})
    assert r.cheapest == ("2026-10-01", "2026-10-05", 90.0)
    assert RouteResult(Route("BGA", "CTG", (2, 5))).cheapest is None


def test_search_routes_continues_on_error_but_stops_on_rate_limit():
    calls, errors = [], []

    def searcher(route, start, end):
        calls.append(route.destination)
        if route.destination == "BAQ":
            raise ValueError("rota")
        if route.destination == "SMR":
            raise RateLimited("HTTP 429")
        return RouteResult(route, {("2026-10-01", "2026-10-03"): 1.0})

    jobs = [(Route("BGA", d, (2, 5)), date(2026, 10, 1), date(2026, 10, 2)) for d in ("CTG", "BAQ", "SMR", "RCH")]
    with pytest.raises(RateLimited) as exc:
        search_routes(jobs, searcher, on_error=lambda key, e: errors.append(key))
    assert calls == ["CTG", "BAQ", "SMR"] and errors == ["BGA-BAQ/2-5n/0m"]
    assert [r.route.destination for r in exc.value.partial] == ["CTG"]
