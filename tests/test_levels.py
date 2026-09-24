from dataclasses import replace
from datetime import timedelta

from cheapflights.config import LevelSettings
from cheapflights.levels import CHEAP, SUPER, best_per_destination, classify, feeder_cost, with_feeder

from .conftest import NOW, TODAY, ZONE, calendar, make_result, runs

LEVELS = LevelSettings()
PLAIN = replace(ZONE, super_price=None, cheap_price=None)


def test_promo_on_many_dates_is_cheap_not_super():
    # tarifa promo en 30 % de las fechas: es "lo barato de siempre", 👍 pero no 🔥
    cal = calendar([86_000] * 30 + [220_000] * 70)
    v = classify("BGA", "MDE", cal, "COP", PLAIN, LEVELS, [], TODAY)
    assert v.level == CHEAP and len(v.same_price_dates) == 29


def test_rare_price_far_below_the_rest_is_super():
    cal = calendar([64_000] * 5 + [80_000] * 30 + [124_000] * 65)
    v = classify("BGA", "BOG", cal, "COP", PLAIN, LEVELS, [], TODAY)
    assert v.level == SUPER and v.stage == 1 and v.price == 64_000


def test_flat_route_is_nothing():
    v = classify("BGA", "AXM", calendar([316_250] * 50), "COP", PLAIN, LEVELS, [], TODAY)
    assert v.level is None and v.savings_percent == 0


def test_fixed_prices_add_to_relative_rules():
    cal = calendar([316_250] * 50)
    z = replace(PLAIN, prices={"AXM": (320_000, 400_000)})
    assert classify("BGA", "AXM", cal, "COP", z, LEVELS, [], TODAY).level == SUPER
    z = replace(PLAIN, prices={"AXM": (None, 330_000)})
    assert classify("BGA", "AXM", cal, "COP", z, LEVELS, [], TODAY).level == CHEAP


def test_today_and_past_dates_are_ignored():
    cal = calendar([10_000], start=TODAY - timedelta(days=2)) | {TODAY.isoformat(): 5_000.0} | calendar([150_000])
    v = classify("BGA", "BOG", cal, "COP", PLAIN, LEVELS, [], TODAY)
    assert v.price == 150_000
    assert classify("BGA", "BOG", {TODAY.isoformat(): 1.0}, "COP", PLAIN, LEVELS, [], TODAY) is None


def test_stage2_needs_enough_history():
    v = classify("BGA", "BOG", calendar([150_000]), "COP", PLAIN, LEVELS, runs([200_000] * 10), TODAY)
    assert v.stage == 1


def test_stage2_super_requires_rank_and_discount():
    past = runs([200_000 + i * 1000 for i in range(25)])
    v = classify("BGA", "BOG", calendar([150_000, 300_000]), "COP", PLAIN, LEVELS, past, TODAY)
    assert v.stage == 2 and v.level == SUPER and v.new_low
    v = classify("BGA", "BOG", calendar([199_000, 200_000]), "COP", PLAIN, LEVELS, past, TODAY)
    assert v.level is None  # nuevo mínimo, pero apenas 1 % bajo lo que suele costar


def test_stage2_flat_route_is_not_cheap():
    v = classify("BGA", "BOG", calendar([316_250]), "COP", PLAIN, LEVELS, runs([316_250] * 30), TODAY)
    assert v.stage == 2 and v.percentile == 50.0 and v.level is None


def test_stage2_fixed_super_still_counts():
    z = replace(PLAIN, prices={"BOG": (90_000, None)})
    v = classify("BGA", "BOG", calendar([85_000, 90_500]), "COP", z, LEVELS, runs([86_000] * 30), TODAY)
    assert v.stage == 2 and v.level == SUPER


def test_other_dates_sorted_by_date_and_really_cheap():
    cal = calendar([300_000] * 10 + [100_000, 300_000, 150_000, 300_000, 120_000] + [300_000] * 10)
    v = classify("BGA", "BOG", cal, "COP", PLAIN, LEVELS, [], TODAY)
    assert v.price == 100_000
    prices = [p for _, p in v.cheap_dates]
    dates = [d for d, _ in v.cheap_dates]
    assert prices == [150_000, 120_000] and dates == sorted(dates)
    assert all(p <= v.cheap_limit for p in prices)


def test_near_normal_uses_dates_around_the_deal():
    cal = calendar([100_000] * 40 + [500_000] * 140)  # barato cerca, carísimo lejos
    v = classify("BGA", "BOG", cal, "COP", PLAIN, LEVELS, [], TODAY)
    assert v.normal == 500_000 and v.near_normal == 100_000 and v.savings_percent == 0


def test_feeder_same_day_day_before_or_estimate(history):
    history.record(make_result("BGA", "BOG", [90_000, 70_000, 95_000]), NOW)
    d1 = (TODAY + timedelta(days=2)).isoformat()
    assert feeder_cost(history, "BGA", "BOG", d1, TODAY) == (70_000, d1, False)
    d2 = (TODAY + timedelta(days=4)).isoformat()
    assert feeder_cost(history, "BGA", "BOG", d2, TODAY) == (95_000, (TODAY + timedelta(days=3)).isoformat(), False)
    far = (TODAY + timedelta(days=250)).isoformat()  # fuera del calendario del tramo: se estima
    assert feeder_cost(history, "BGA", "BOG", far, TODAY) == (90_000, None, True)
    assert feeder_cost(history, "BGA", "BGA", d1, TODAY) is None


def test_best_per_destination_prefers_lowest_total(history, config):
    zone = config.zone("Perú, Ecuador, Bolivia y Venezuela")
    history.record(make_result("BGA", "BOG", [150_000] * 5), NOW)
    history.record(make_result("BGA", "MDE", [90_000] * 5), NOW)
    a = with_feeder(classify("BOG", "LIM", calendar([600_000, 500_000]), "COP", zone, LEVELS, [], TODAY), history, "BGA", TODAY)
    b = with_feeder(classify("MDE", "LIM", calendar([600_000, 520_000]), "COP", zone, LEVELS, [], TODAY), history, "BGA", TODAY)
    assert a.total == 650_000 and b.total == 610_000
    assert best_per_destination([a, b])[0].origin == "MDE"
