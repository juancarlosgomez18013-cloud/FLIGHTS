from datetime import timedelta

from cheapflights.history import History, midrank_percentile
from cheapflights.search import RouteResult

from .conftest import NOW, make_result


def test_record_tracks_best_last_and_runs(history):
    history.record(make_result(prices=[300_000, 250_000]), NOW)
    assert history.best("BGA-BOG")["price"] == 250_000
    history.record(make_result(prices=[200_000, 260_000]), NOW + timedelta(hours=6))
    assert history.best("BGA-BOG")["price"] == 200_000
    assert history.last("BGA-BOG")["price"] == 200_000
    assert len(history.runs("BGA-BOG")) == 2


def test_save_and_load_roundtrip(history):
    history.record(make_result(), NOW)
    history.mark_alerted("BOG", 150_000, "2026-10-01", "BGA-BOG", NOW)
    history.save()
    loaded = History.load(history.path)
    assert loaded.best("BGA-BOG")["price"] == 150_000
    assert loaded.data["alerts"]["BOG"]["price"] == 150_000


def test_empty_result_keeps_calendar(history):
    history.record(make_result(prices=[100_000]), NOW)
    history.record(RouteResult("BGA", "BOG", {}), NOW + timedelta(hours=6))
    assert history.calendar("BGA-BOG")
    assert history.runs("BGA-BOG")[-1]["min_price"] is None
    assert history.runs_before_current_calendar("BGA-BOG") == []


def test_midrank_percentile_handles_ties():
    assert midrank_percentile([100, 100, 100], 100) == 50.0  # precio plano = normal, no "nunca visto"
    assert midrank_percentile([100, 200, 300, 400, 500], 250) == 40.0
    assert midrank_percentile([100, 200], 50) == 0.0
    assert midrank_percentile([], 50) is None


def test_alert_once_then_only_if_cheaper_or_reappears(history):
    assert history.should_alert("BOG", 100_000, 5)
    history.mark_alerted("BOG", 100_000, "2026-10-01", "BGA-BOG", NOW)
    assert not history.should_alert("BOG", 100_000, 5)  # mismo precio: no se repite
    assert not history.should_alert("BOG", 96_000, 5)  # bajó solo 4 %
    assert history.should_alert("BOG", 95_000, 5)  # bajó 5 %
    history.clear_alert("BOG")  # la oferta desapareció
    assert history.should_alert("BOG", 100_000, 5)  # si vuelve, se avisa de nuevo
    assert history.should_alert("MDE", 100_000, 5)


def test_legacy_alerted_key_is_dropped():
    h = History({"routes": {"BGA-BOG": {"best": None, "last": None, "runs": [], "calendar": {}, "alerted": {"x": 1}}}})
    assert "alerted" not in h.route("BGA-BOG")
    assert h.data["version"] == 2 and h.data["alerts"] == {}
