from datetime import datetime, timedelta, timezone

from cheapflights.alerts import evaluate
from cheapflights.config import AlertSettings, Group
from cheapflights.history import History

GROUP = Group(name="Colombia", kind="domestic", origins=("BGA",), destinations=("BOG",), target_price=140_000)
SETTINGS = AlertSettings(drop_percent=15, new_low=True, cooldown_hours=24)


def test_record_tracks_best_and_last(history, make_route_result):
    prev = history.record(make_route_result(prices=[300_000, 250_000]))
    assert prev["best"] is None
    assert history.best("BGA-BOG")["price"] == 250_000
    prev = history.record(make_route_result(prices=[200_000, 260_000]))
    assert prev["best"]["price"] == 250_000
    assert history.best("BGA-BOG")["price"] == 200_000
    assert history.last("BGA-BOG")["price"] == 200_000
    assert len(history.route("BGA-BOG")["runs"]) == 2


def test_save_and_load_roundtrip(history, make_route_result):
    history.record(make_route_result())
    history.save()
    loaded = History.load(history.path)
    assert loaded.best("BGA-BOG")["price"] == 150_000
    assert loaded.calendar("BGA-BOG")


def test_first_run_only_target_alert(history, make_route_result):
    result = make_route_result(prices=[200_000, 120_000])
    prev = history.record(result)
    alerts = evaluate(result, prev, GROUP, SETTINGS, history)
    assert [a.kind for a in alerts] == ["target"]
    assert alerts[0].price == 120_000


def test_first_run_no_alert_above_target(history, make_route_result):
    result = make_route_result(prices=[200_000, 180_000])
    prev = history.record(result)
    assert evaluate(result, prev, GROUP, SETTINGS, history) == []


def test_new_low_alert(history, make_route_result):
    r1 = make_route_result(prices=[300_000, 250_000])
    history.record(r1)
    r2 = make_route_result(prices=[300_000, 240_000])
    prev = history.record(r2)
    alerts = evaluate(r2, prev, GROUP, SETTINGS, history)
    assert [a.kind for a in alerts] == ["new_low"]
    assert alerts[0].previous == 250_000


def test_drop_alert_without_new_low(history, make_route_result):
    history.record(make_route_result(prices=[100_000]))  # best = 100k
    history.record(make_route_result(prices=[400_000]))  # last = 400k
    r3 = make_route_result(prices=[300_000])  # 25% drop, not a new low
    prev = history.record(r3)
    alerts = evaluate(r3, prev, GROUP, SETTINGS, history)
    assert [a.kind for a in alerts] == ["drop"]


def test_target_wins_over_other_kinds(history, make_route_result):
    history.record(make_route_result(prices=[200_000]))
    r2 = make_route_result(prices=[100_000])
    prev = history.record(r2)
    alerts = evaluate(r2, prev, GROUP, SETTINGS, history)
    assert len(alerts) == 1 and alerts[0].kind == "target"


def test_cooldown_suppresses_repeat(history, make_route_result):
    now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    r = make_route_result(prices=[120_000])
    prev = history.record(r, now=now)
    assert evaluate(r, prev, GROUP, SETTINGS, history, now=now)
    prev = history.record(r, now=now + timedelta(hours=6))
    assert evaluate(r, prev, GROUP, SETTINGS, history, now=now + timedelta(hours=6)) == []
    prev = history.record(r, now=now + timedelta(hours=30))
    assert evaluate(r, prev, GROUP, SETTINGS, history, now=now + timedelta(hours=30))


def test_cooldown_bypassed_when_price_falls_further(history, make_route_result):
    now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    r = make_route_result(prices=[120_000])
    prev = history.record(r, now=now)
    assert evaluate(r, prev, GROUP, SETTINGS, history, now=now)
    cheaper = make_route_result(prices=[100_000])
    prev = history.record(cheaper, now=now + timedelta(hours=1))
    assert evaluate(cheaper, prev, GROUP, SETTINGS, history, now=now + timedelta(hours=1))


def test_percentile_needs_history(history, make_route_result):
    for p in [100, 200, 300, 400]:
        history.record(make_route_result(prices=[p * 1000]))
    assert history.price_percentile("BGA-BOG", 250_000) is None
    history.record(make_route_result(prices=[500_000]))
    assert history.price_percentile("BGA-BOG", 250_000) == 40.0


def test_empty_result_does_not_break(history):
    from cheapflights.search import RouteResult

    r = RouteResult(origin="BGA", destination="LET", calendar={})
    prev = history.record(r)
    assert history.best("BGA-LET") is None
    assert evaluate(r, prev, GROUP, SETTINGS, history) == []
