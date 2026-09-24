from dataclasses import replace
from datetime import timedelta

from cheapflights.config import LevelSettings
from cheapflights.levels import CHEAP, SUPER, best_per_destination, classify, classify_from_history, classify_trip, combine, enrich, feeder_cost
from cheapflights.search import Route, RouteResult

from .conftest import NOW, TODAY, ZONE, fares, route, runs

LEVELS = LevelSettings()
PLAIN = replace(ZONE, super_price=None, cheap_price=None)
R = route()


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def test_promo_on_many_dates_is_cheap_not_super():
    # tarifa promo uno de cada tres días: es "lo barato de siempre", 👍 pero no 🔥
    v = classify(route("BGA", "MDE"), fares([86_000, 220_000, 220_000] * 33), "COP", PLAIN, LEVELS, [], TODAY)
    assert v.level == CHEAP and v.savings_percent > 45 and v.share > 30


def test_rare_price_far_below_the_rest_is_super():
    v = classify(R, fares([220_000] * 20 + [100_000] + [220_000] * 80), "COP", PLAIN, LEVELS, [], TODAY)
    assert v.level == SUPER and v.stage == 1 and v.price == 100_000 and v.nights == 2 and v.share < 3


def test_rare_but_not_deep_enough_is_only_cheap():
    v = classify(R, fares([220_000] * 20 + [140_000] + [220_000] * 80), "COP", PLAIN, LEVELS, [], TODAY)
    assert v.level == CHEAP and round(v.savings_percent) == 36  # 36 % es barato, no 🔥 en modo muy estricto


def test_compares_with_cheapest_trip_per_day_not_all_combinations():
    # cada día: una vuelta barata (200.000) y varias caras; la oferta de 150.000 es solo 25 % bajo lo normal
    f = {}
    for i in range(60):
        out = TODAY + timedelta(days=1 + i)
        for n, p in ((2, 200_000.0), (3, 500_000.0), (4, 600_000.0), (5, 700_000.0)):
            f[(out.isoformat(), (out + timedelta(days=n)).isoformat())] = p
    f[(_iso(20), _iso(22))] = 150_000.0
    v = classify(R, f, "COP", PLAIN, LEVELS, [], TODAY)
    assert v.near_normal == 200_000 and v.level == CHEAP


def test_flat_route_is_nothing():
    v = classify(route("BGA", "AXM"), fares([316_250] * 50), "COP", PLAIN, LEVELS, [], TODAY)
    assert v.level is None and v.savings_percent == 0


def test_fixed_prices_add_to_relative_rules():
    f = fares([316_250] * 50)
    z = replace(PLAIN, prices={"AXM": (320_000, 400_000)})
    assert classify(route("BGA", "AXM"), f, "COP", z, LEVELS, [], TODAY).level == SUPER
    z = replace(PLAIN, prices={"AXM": (None, 330_000)})
    assert classify(route("BGA", "AXM"), f, "COP", z, LEVELS, [], TODAY).level == CHEAP


def test_today_and_past_dates_are_ignored():
    f = fares([10_000], start=TODAY - timedelta(days=2)) | {(_iso(0), _iso(2)): 5_000.0} | fares([150_000])
    assert classify(R, f, "COP", PLAIN, LEVELS, [], TODAY).price == 150_000
    assert classify(R, {(_iso(0), _iso(2)): 1.0}, "COP", PLAIN, LEVELS, [], TODAY) is None


def test_cheapest_combination_wins_and_nights_follow_it():
    f = {(_iso(10), _iso(12)): 300_000.0, (_iso(10), _iso(14)): 210_000.0} | fares([300_000] * 30)
    v = classify(R, f, "COP", PLAIN, LEVELS, [], TODAY)
    assert (v.out, v.back, v.nights, v.price) == (_iso(10), _iso(14), 4, 210_000)


def test_stage2_needs_enough_history():
    v = classify(R, fares([150_000]), "COP", PLAIN, LEVELS, runs([200_000] * 10), TODAY)
    assert v.stage == 1


def test_stage2_super_requires_rank_and_discount():
    past = runs([200_000 + i * 1000 for i in range(25)])
    v = classify(R, fares([150_000] + [300_000] * 40), "COP", PLAIN, LEVELS, past, TODAY)
    assert v.stage == 2 and v.level == SUPER and v.new_low
    v = classify(R, fares([199_000, 200_000]), "COP", PLAIN, LEVELS, past, TODAY)
    assert v.level is None  # nuevo mínimo, pero apenas 1 % bajo lo que suele costar


def test_stage2_flat_route_is_not_cheap():
    v = classify(R, fares([316_250]), "COP", PLAIN, LEVELS, runs([316_250] * 30), TODAY)
    assert v.stage == 2 and v.percentile == 50.0 and v.level is None


def test_stage2_fixed_super_still_counts():
    z = replace(PLAIN, prices={"BOG": (90_000, None)})
    v = classify(R, fares([85_000, 90_500]), "COP", z, LEVELS, runs([86_000] * 30), TODAY)
    assert v.stage == 2 and v.level == SUPER


def test_other_trips_sorted_by_date_and_really_cheap():
    f = fares([300_000] * 10 + [100_000, 300_000, 150_000, 300_000, 120_000] + [300_000] * 10)
    v = classify(R, f, "COP", PLAIN, LEVELS, [], TODAY)
    assert v.price == 100_000
    prices = [p for _, _, p in v.cheap_trips]
    outs = [o for o, _, _ in v.cheap_trips]
    assert prices == [150_000, 120_000] and outs == sorted(outs)
    assert all(p <= v.cheap_limit for p in prices)


def test_near_normal_uses_dates_around_the_deal():
    f = fares([100_000] * 40 + [500_000] * 140)  # barato cerca, carísimo lejos
    v = classify(R, f, "COP", PLAIN, LEVELS, [], TODAY)
    assert v.normal == 500_000 and v.near_normal == 100_000 and v.savings_percent == 0


def test_feeder_matches_the_trip_dates(history, config):
    feeder = config.feeder_route("BOG", 1)
    assert feeder == Route("BGA", "BOG", (6, 16), 1)  # noches internacionales + margen para salir antes y volver después
    out, back = _iso(50), _iso(58)  # 8 noches
    f = {
        (out, back): 200_000.0,
        (_iso(49), _iso(59)): 180_000.0,  # sale el día anterior y vuelve el siguiente: encaja y es más barato
        (_iso(49), back): 190_000.0,
        (_iso(90), _iso(98)): 500_000.0,
    }
    history.record(RouteResult(feeder, f), NOW)
    assert feeder_cost(history, feeder, out, back, TODAY) == (180_000, _iso(49), _iso(59), False)
    # sin fechas que encajen: se estima con el precio normal de la conexión
    assert feeder_cost(history, feeder, _iso(120), _iso(128), TODAY) == (195_000, None, None, True)
    assert feeder_cost(history, Route("BGA", "XXX", (6, 16), 1), out, back, TODAY) is None


def test_enrich_adds_feeder_and_other_bag_price(history, config):
    zone = config.zone("Perú, Ecuador, Bolivia y Venezuela")
    r = zone.route("BOG", "LIM")
    assert r.bags == 1 and r.nights == (6, 14)
    out, back = _iso(50), _iso(58)
    history.record(RouteResult(config.feeder_route("BOG", 1), {(_iso(49), _iso(59)): 150_000.0}), NOW)
    history.record(RouteResult(r.other_bags, {(out, back): 400_000.0}), NOW, partial=True)
    v = classify(r, {(out, back): 400_000.0} | fares([900_000] * 60, nights=(6, 14)), "COP", zone, LEVELS, [], TODAY)
    v = enrich(v, history, config, TODAY)
    assert v.level == SUPER and v.feeder_price == 150_000 and v.total == 550_000
    assert (v.feeder_out, v.feeder_back, v.feeder_origin) == (_iso(49), _iso(59), "BGA")
    assert v.other_bag_price == 400_000


def test_best_per_destination_prefers_lowest_total(history, config):
    zone = config.zone("Perú, Ecuador, Bolivia y Venezuela")
    out, back = _iso(50), _iso(57)
    history.record(RouteResult(config.feeder_route("BOG", 1), {(out, back): 150_000.0}), NOW)
    history.record(RouteResult(config.feeder_route("MDE", 1), {(out, back): 90_000.0}), NOW)
    a = enrich(classify(zone.route("BOG", "LIM"), {(out, back): 500_000.0, (_iso(60), _iso(67)): 600_000.0}, "COP", zone, LEVELS, [], TODAY), history, config, TODAY)
    b = enrich(classify(zone.route("MDE", "LIM"), {(out, back): 520_000.0, (_iso(60), _iso(67)): 600_000.0}, "COP", zone, LEVELS, [], TODAY), history, config, TODAY)
    assert a.total == 650_000 and b.total == 610_000
    assert best_per_destination([a, b])[0].origin == "MDE"


def test_classify_from_history_ignores_partial_searches(history):
    other = route(bags=1)
    history.record(RouteResult(other, fares([100_000] * 5)), NOW, partial=True)
    assert classify_from_history(PLAIN, other, history, LEVELS, TODAY) is None
    history.record(RouteResult(R, fares([100_000] * 5)), NOW)
    assert classify_from_history(PLAIN, R, history, LEVELS, TODAY).price == 100_000


def _one_way(prices, **kw):
    return {(d, d): p for (d, _), p in fares(prices, **kw).items()}


def test_one_way_ignores_round_trip_fixed_prices():
    z = replace(PLAIN, prices={"BOG": (200_000, 250_000)})  # precios fijos pensados para ida y vuelta
    v = classify(route("BGA", "BOG", (0, 0)), _one_way([150_000] * 40), "COP", z, LEVELS, [], TODAY)
    assert v.one_way and v.level is None  # un tramo plano a 150.000 no es 🔥 aunque sea < 200.000
    assert classify(R, fares([150_000] * 40), "COP", z, LEVELS, [], TODAY).level == SUPER


def test_combine_picks_cheapest_way_per_trip_in_any_dates():
    rt = {(_iso(10), _iso(13)): 180_000.0, (_iso(20), _iso(22)): 90_000.0}
    ida = {(_iso(10), _iso(10)): 60_000.0, (_iso(20), _iso(20)): 70_000.0}
    regreso = {(_iso(13), _iso(13)): 70_000.0, (_iso(14), _iso(14)): 40_000.0, (_iso(22), _iso(22)): 50_000.0, (_iso(40), _iso(40)): 1.0}
    fares, legs = combine(rt, ida, regreso, (2, 5))
    assert fares[(_iso(10), _iso(13))] == 130_000 and legs[(_iso(10), _iso(13))] == (60_000, 70_000)  # armado gana
    assert fares[(_iso(10), _iso(14))] == 100_000 and legs[(_iso(10), _iso(14))] == (60_000, 40_000)  # fechas sin ida y vuelta
    assert fares[(_iso(20), _iso(22))] == 90_000 and (_iso(20), _iso(22)) not in legs  # el ida y vuelta normal gana
    assert (_iso(10), _iso(40)) not in fares  # 30 noches: fuera del rango


def test_best_trip_can_be_armado_with_two_airlines(history, config):
    zone = config.zone("Costa Caribe")
    r = zone.route("BGA", "CTG")
    history.record(RouteResult(r, fares([320_000] * 60)), NOW)  # ida y vuelta normal: siempre $320.000
    history.record(RouteResult(r.outbound, {(d, d): 170_000.0 for d, _ in fares([1] * 60)} | {(_iso(20), _iso(20)): 52_000.0}), NOW)
    history.record(RouteResult(r.inbound, {(d, d): 170_000.0 for d, _ in fares([1] * 60)} | {(_iso(23), _iso(23)): 66_000.0}), NOW)
    v = classify_trip(zone, r, history, LEVELS, [], TODAY)
    assert v.armado and v.legs == (52_000, 66_000) and v.price == 118_000
    assert (v.out, v.back) == (_iso(20), _iso(23)) and v.level == SUPER and v.alert_key == "CTG"
    assert v.route.combo and v.key == "BGA-CTG/2-5n/0m/armado"
    assert enrich(v, history, config, TODAY).other_bag_price is None  # la otra maleta no aplica al armado
    assert classify_from_history(zone, r, history, LEVELS, TODAY).legs == (52_000, 66_000)


def test_one_way_verdicts_are_kept_apart_from_round_trips():
    ow = classify(route("BGA", "BOG", (0, 0)), _one_way([50_000] + [120_000] * 30), "COP", PLAIN, LEVELS, [], TODAY)
    back = classify(route("BOG", "BGA", (0, 0)), _one_way([55_000] + [120_000] * 30), "COP", PLAIN, LEVELS, [], TODAY)
    rt = classify(R, fares([100_000] + [240_000] * 30), "COP", PLAIN, LEVELS, [], TODAY)
    kept = best_per_destination([ow, back, rt])
    assert sorted(v.alert_key for v in kept) == ["BOG", "solo-ida:BGA-BOG", "solo-ida:BOG-BGA"]
