from datetime import timedelta

from cheapflights.history import History, midrank_percentile, pack_fares, unpack_fares
from cheapflights.search import RouteResult

from .conftest import NOW, make_result, route

KEY = route().key  # BGA-BOG/2-5n/0m


def test_record_tracks_best_last_and_runs(history):
    history.record(make_result(prices=[300_000, 250_000]), NOW)
    assert history.best(KEY)["price"] == 250_000
    history.record(make_result(prices=[200_000, 260_000]), NOW + timedelta(hours=6))
    assert history.best(KEY)["price"] == 200_000
    assert history.last(KEY)["price"] == 200_000 and history.last(KEY)["out"] < history.last(KEY)["back"]
    assert len(history.runs(KEY)) == 2
    assert history.route_of(KEY) == route()


def test_fares_are_stored_compactly_and_round_trip():
    fares = {
        ("2026-10-01", "2026-10-03"): 100.0,
        ("2026-10-01", "2026-10-06"): 200.0,
        ("2026-10-02", "2026-10-05"): 150.0,
    }
    packed = pack_fares(fares, (2, 5))
    assert packed == {"2026-10-01": [100, None, None, 200], "2026-10-02": [None, 150, None, None]}
    assert unpack_fares(packed, (2, 5)) == fares
    assert pack_fares({("2026-10-01", "2026-10-09"): 1.0}, (2, 5)) == {}  # fuera del rango de noches


def test_save_and_load_roundtrip(history):
    history.record(make_result(), NOW)
    history.mark_alerted("BOG", 150_000, "2026-10-01", "2026-10-03", KEY, NOW)
    history.save()
    loaded = History.load(history.path)
    assert loaded.best(KEY)["price"] == 150_000
    assert loaded.fares(KEY) == history.fares(KEY)
    assert loaded.data["alerts"]["BOG"]["price"] == 150_000 and loaded.data["version"] == 3


def test_empty_result_keeps_fares(history):
    history.record(make_result(prices=[100_000]), NOW)
    history.record(RouteResult(route(), {}), NOW + timedelta(hours=6))
    assert history.fares(KEY)
    assert history.runs(KEY)[-1]["min_price"] is None
    assert history.runs_before_current_fares(KEY) == []


def test_partial_search_stores_fares_but_not_runs(history):
    other = route(bags=1)
    history.record(make_result(bags=1, prices=[150_000]), NOW, partial=True)
    assert history.is_partial(other.key) and history.runs(other.key) == []
    assert history.fares(other.key) and history.last_seen(other.key) == NOW
    history.record(make_result(bags=1, prices=[140_000]), NOW + timedelta(hours=1))  # búsqueda completa
    assert not history.is_partial(other.key) and len(history.runs(other.key)) == 1
    assert sorted(history.keys_for_pair("BGA-BOG")) == [other.key]


def test_old_one_way_history_is_discarded():
    old = {"version": 2, "routes": {"BGA-BOG": {"best": None, "calendar": {"2026-10-01": 1}}}, "alerts": {"BOG": {"price": 1}}}
    h = History(old)
    assert h.data["routes"] == {} and h.data["alerts"] == {} and h.data["version"] == 3


def test_midrank_percentile_handles_ties():
    assert midrank_percentile([100, 100, 100], 100) == 50.0  # precio plano = normal, no "nunca visto"
    assert midrank_percentile([100, 200, 300, 400, 500], 250) == 40.0
    assert midrank_percentile([100, 200], 50) == 0.0
    assert midrank_percentile([], 50) is None


def test_alert_once_then_only_if_cheaper_or_reappears(history):
    assert history.should_alert("BOG", 100_000, 5)
    history.mark_alerted("BOG", 100_000, "2026-10-01", "2026-10-03", KEY, NOW)
    assert not history.should_alert("BOG", 100_000, 5)  # mismo precio: no se repite
    assert not history.should_alert("BOG", 96_000, 5)  # bajó solo 4 %
    assert history.should_alert("BOG", 95_000, 5)  # bajó 5 %
    history.clear_alert("BOG")  # la oferta desapareció
    assert history.should_alert("BOG", 100_000, 5)  # si vuelve, se avisa de nuevo
    assert history.should_alert("MDE", 100_000, 5)
