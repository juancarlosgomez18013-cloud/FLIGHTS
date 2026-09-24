"""Clasificación de precios: 🔥 súper barato, 👍 barato o nada.

Cada "viaje" es una combinación (fecha de ida, fecha de vuelta) dentro del rango de noches de la
zona; en solo ida, la vuelta es el mismo día. Para no inflar las ofertas, primero se toma el viaje
más barato que sale cada día y todo se compara contra eso.

"Precio normal" = mediana de esos precios por día de salida, en las fechas cercanas a la oferta
(±30 días), que es lo que suele costar viajar por esas fechas.

Etapa 1 (poco historial):
  🔥 si está al menos X % bajo el precio normal Y ese precio aparece en muy pocas fechas
     (la tarifa promo que se repite en muchos días no es 🔥, es 👍).
  👍 si está al menos Y % bajo el precio normal.
Etapa 2 (historial suficiente): además se compara con lo que la ruta ha costado en el tiempo.
  🔥 si está en el P % más barato de lo visto, al menos D % bajo lo que suele costar y es raro.
En ambas etapas, los precios fijos opcionales de config.yaml también cuentan.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

from .config import Config, LevelSettings, Zone
from .history import History, midrank_percentile, parse_ts
from .search import Fares, Route, nights_between

SUPER = "super"
CHEAP = "barato"
LEVEL_RANK = {SUPER: 0, CHEAP: 1, None: 2}
NEAR_DAYS = 30  # "cerca de esa fecha" = ±30 días de la fecha de ida


@dataclass(frozen=True)
class Verdict:
    zone: Zone
    route: Route  # la búsqueda que decide (con la maleta de la zona)
    price: float
    out: str  # fecha de ida
    back: str  # fecha de vuelta
    currency: str
    normal: float  # mediana de todos los viajes próximos
    near_normal: float  # mediana de los viajes que salen a ±30 días de la oferta (comparación honesta)
    level: str | None
    stage: int  # 1 = frente a otros viajes, 2 = frente al historial
    cheap_limit: float  # hasta qué precio un viaje cuenta como barato
    percentile: float | None = None
    usual: float | None = None
    share: float = 0.0  # % de fechas de salida con este mismo precio (±1 %): bajo = oferta rara
    tracked_days: float | None = None
    new_low: bool = False
    same_price_trips: tuple[tuple[str, str], ...] = ()  # otros viajes al mismo precio (±1 %)
    cheap_trips: tuple[tuple[str, str, float], ...] = ()  # otros viajes baratos (precio distinto), por fecha
    other_bag_price: float | None = None  # el mismo viaje con la otra opción de maleta
    legs: tuple[float, float] | None = None  # viaje armado con dos tramos solo ida: (precio ida, precio regreso)
    feeder_price: float | None = None  # conexión casa ⇄ hub, ida y vuelta
    feeder_out: str | None = None
    feeder_back: str | None = None
    feeder_origin: str | None = None
    feeder_estimated: bool = False

    @property
    def origin(self) -> str:
        return self.route.origin

    @property
    def destination(self) -> str:
        return self.route.destination

    @property
    def bags(self) -> int:
        return self.route.bags

    @property
    def key(self) -> str:
        return self.route.key

    @property
    def one_way(self) -> bool:
        return self.route.one_way

    @property
    def armado(self) -> bool:
        """True si el precio es la suma de dos tramos solo ida (posiblemente de aerolíneas distintas)."""
        return self.legs is not None

    @property
    def alert_key(self) -> str:
        """Qué se avisa una sola vez: el destino (ida y vuelta, desde cualquier hub) o el tramo solo ida."""
        return f"solo-ida:{self.pair}" if self.one_way else self.destination

    @property
    def pair(self) -> str:
        return self.route.pair

    @property
    def nights(self) -> int:
        return nights_between(self.out, self.back)

    @property
    def total(self) -> float:
        return self.price + (self.feeder_price or 0.0)

    @property
    def same_price_outs(self) -> tuple[str, ...]:
        """Fechas de ida distintas (sin repetir) con el mismo precio."""
        return tuple(sorted({o for o, _ in self.same_price_trips} - {self.out}))

    @property
    def savings_percent(self) -> float:
        """Cuánto más barato que lo que suele costar cerca de esa fecha (0 si no aplica)."""
        if not self.near_normal or self.near_normal <= self.price:
            return 0.0
        return 100 * (1 - self.price / self.near_normal)


def _history_span(runs: list[dict[str, Any]]) -> tuple[int, float]:
    priced = [r for r in runs if r.get("min_price")]
    if len(priced) < 2:
        return len(priced), 0.0
    first = parse_ts(priced[0]["seen_at"])
    last = parse_ts(priced[-1]["seen_at"])
    return len(priced), (last - first).total_seconds() / 86400


def cheapest_per_day(fares: Fares) -> dict[str, float]:
    """El viaje más barato que sale cada día (sea cual sea la vuelta)."""
    days: dict[str, float] = {}
    for (out, _), price in fares.items():
        if out not in days or price < days[out]:
            days[out] = price
    return days


def _near_normal(per_day: dict[str, float], out: str, fallback: float) -> float:
    d = date.fromisoformat(out)
    lo, hi = (d - timedelta(days=NEAR_DAYS)).isoformat(), (d + timedelta(days=NEAR_DAYS)).isoformat()
    near = [p for day, p in per_day.items() if lo <= day <= hi]
    return statistics.median(near) if len(near) >= 10 else fallback


def upcoming_fares(fares: Fares, today: date) -> Fares:
    """Viajes que salen desde mañana: uno de hoy probablemente ya salió o no se alcanza a tomar."""
    return {k: float(p) for k, p in fares.items() if k[0] > today.isoformat() and p and p > 0}


def classify(
    route: Route,
    fares: Fares,
    currency: str,
    zone: Zone,
    levels: LevelSettings,
    past_runs: list[dict[str, Any]],
    today: date,
) -> Verdict | None:
    """Clasifica el viaje más barato de una ruta. `past_runs` = búsquedas ANTERIORES a estos precios."""
    upcoming = upcoming_fares(fares, today)
    if not upcoming:
        return None
    (out, back), price = min(upcoming.items(), key=lambda kv: (kv[1], kv[0]))
    per_day = cheapest_per_day(upcoming)
    day_prices = list(per_day.values())
    normal = statistics.median(day_prices)
    reference = _near_normal(per_day, out, normal)  # lo que suele costar salir por esas fechas
    share = 100 * sum(1 for p in day_prices if p <= price * 1.01) / len(day_prices)
    rare = share <= levels.super_max_share
    discount_now = 100 * (1 - price / reference) if reference else 0.0
    # Los precios fijos de config.yaml son de ida y vuelta: no aplican a un tramo solo ida.
    fixed_super, fixed_cheap = (None, None) if route.one_way else zone.fixed_prices(route.destination)

    cheap_limit = reference * (1 - levels.cheap_below_normal / 100)
    if fixed_cheap is not None:
        cheap_limit = max(cheap_limit, fixed_cheap)
    relative_super = discount_now >= levels.super_below_normal and rare
    is_fixed_super = fixed_super is not None and price <= fixed_super
    is_cheap = price <= cheap_limit

    mins = [float(r["min_price"]) for r in past_runs if r.get("min_price")]
    count, span_days = _history_span(past_runs)
    mature = count >= levels.history_min_runs and span_days >= levels.history_min_days
    new_low = bool(mins) and price < min(mins)

    percentile = usual = None
    level = None
    if mature:
        stage = 2
        percentile = midrank_percentile(mins, price)
        usual = statistics.median(mins)
        discount = 100 * (1 - price / usual) if usual else 0.0
        if (percentile <= levels.super_percentile and discount >= levels.super_min_discount and rare) or is_fixed_super:
            level = SUPER
        elif (percentile <= levels.cheap_percentile and discount >= levels.cheap_min_discount) or is_cheap:
            level = CHEAP
    else:
        stage = 1
        if relative_super or is_fixed_super:
            level = SUPER
        elif is_cheap:
            level = CHEAP

    same = tuple(sorted(k for k, p in upcoming.items() if k != (out, back) and p <= price * 1.01))
    others = tuple(sorted((o, b, p) for (o, b), p in upcoming.items() if (o, b) != (out, back) and price * 1.01 < p <= cheap_limit))

    return Verdict(
        zone=zone,
        route=route,
        price=price,
        out=out,
        back=back,
        currency=currency,
        normal=normal,
        near_normal=reference,
        level=level,
        stage=stage,
        cheap_limit=cheap_limit,
        percentile=percentile,
        usual=usual,
        tracked_days=span_days if count >= 2 else None,
        new_low=new_low,
        share=share,
        same_price_trips=same,
        cheap_trips=others,
    )


def other_bag_price(history: History, route: Route, out: str, back: str) -> float | None:
    """Precio del mismo viaje con la otra opción de maleta, si se buscó."""
    return history.fares(route.other_bags.key).get((out, back))


def with_other_bag(v: Verdict, history: History) -> Verdict:
    if v.one_way or v.armado:
        return v
    return replace(v, other_bag_price=other_bag_price(history, v.route.base, v.out, v.back))


def combine(round_trip: Fares, outbound: Fares, inbound: Fares, nights: tuple[int, int]) -> tuple[Fares, dict[tuple[str, str], tuple[float, float]]]:
    """El mejor precio de cada viaje (ida, vuelta): ida y vuelta normal o dos tramos solo ida sueltos.

    Devuelve (precios, tramos) donde `tramos[(ida, vuelta)] = (precio ida, precio regreso)` solo para
    los viajes en que armarlo con dos tramos sale más barato (o no hay ida y vuelta para esas fechas).
    """
    merged: Fares = dict(round_trip)
    legs: dict[tuple[str, str], tuple[float, float]] = {}
    back_by_day = {day: price for (day, _), price in inbound.items()}
    lo, hi = nights
    for (out, _), price_out in outbound.items():
        start = date.fromisoformat(out)
        for n in range(lo, hi + 1):
            back = (start + timedelta(days=n)).isoformat()
            price_back = back_by_day.get(back)
            if price_back is None:
                continue
            total = price_out + price_back
            if total < merged.get((out, back), float("inf")):
                merged[(out, back)] = total
                legs[(out, back)] = (price_out, price_back)
    return merged, legs


def trip_fares(history: History, route: Route) -> tuple[Fares, dict[tuple[str, str], tuple[float, float]]]:
    """Precios del mejor viaje (normal o armado) desde lo guardado de sus partes."""
    base = route.base
    round_trip = {} if history.is_partial(base.key) else history.fares(base.key)
    return combine(round_trip, history.fares(base.outbound.key), history.fares(base.inbound.key), base.nights)


def classify_trip(zone: Zone, route: Route, history: History, levels: LevelSettings, past_runs: list[dict[str, Any]], today: date) -> Verdict | None:
    """Clasifica el mejor viaje a un destino: ida y vuelta normal o armado con dos tramos solo ida."""
    fares, legs = trip_fares(history, route)
    if not fares:
        return None
    combo = replace(route.base, combo=True)
    currency = history.currency(route.base.key) or history.currency(route.base.outbound.key)
    v = classify(combo, fares, currency, zone, levels, past_runs, today)
    if v and (v.out, v.back) in legs:
        v = replace(v, legs=legs[(v.out, v.back)])
    return v


def feeder_cost(
    history: History, feeder: Route, out: str, back: str, today: date
) -> tuple[float, str | None, str | None, bool] | None:
    """Conexión casa ⇄ hub, ida y vuelta, que encaje con el viaje: sale el mismo día o el anterior
    y vuelve el mismo día o el siguiente.

    Devuelve (precio, ida, vuelta, estimado). Si no hay precio para esas fechas pero sí para otras,
    usa el precio normal de la conexión como estimado para que el total nunca desaparezca.
    """
    fares = upcoming_fares(history.fares(feeder.key), today)
    if not fares:
        return None
    o, b = date.fromisoformat(out), date.fromisoformat(back)
    options = []
    for fo in (o, o - timedelta(days=1)):
        for fb in (b, b + timedelta(days=1)):
            k = (fo.isoformat(), fb.isoformat())
            if k in fares:
                options.append((fares[k], k))
    if options:
        price, (fo, fb) = min(options)
        return price, fo, fb, False
    return statistics.median(fares.values()), None, None, True


def with_feeder(v: Verdict, history: History, config: Config, today: date) -> Verdict:
    if v.zone.kind != "international" or v.origin == config.home:
        return v
    feeder = config.feeder_route(v.origin, v.bags)
    if feeder is None:
        return v
    cost = feeder_cost(history, feeder, v.out, v.back, today)
    if cost is None:
        return replace(v, feeder_origin=config.home)
    price, fo, fb, estimated = cost
    return replace(v, feeder_price=price, feeder_out=fo, feeder_back=fb, feeder_origin=config.home, feeder_estimated=estimated)


def enrich(v: Verdict, history: History, config: Config, today: date) -> Verdict:
    """Completa un veredicto con el precio de la otra maleta, los dos tramos sueltos y la conexión desde casa."""
    if v.one_way:
        return v
    return with_feeder(with_other_bag(v, history), history, config, today)


def best_per_destination(verdicts: list[Verdict]) -> list[Verdict]:
    """Si un destino sale desde Bogotá y desde Medellín, se queda el más barato en total desde casa.
    Los tramos solo ida van aparte (uno por sentido)."""
    best: dict[str, Verdict] = {}
    for v in verdicts:
        cur = best.get(v.alert_key)
        key = (v.total, LEVEL_RANK[v.level], v.out)
        if cur is None or key < (cur.total, LEVEL_RANK[cur.level], cur.out):
            best[v.alert_key] = v
    return list(best.values())


def classify_from_history(zone: Zone, route: Route, history: History, levels: LevelSettings, today: date) -> Verdict | None:
    """Clasifica usando los precios guardados (para el resumen y el plan, sin buscar de nuevo)."""
    if zone.one_way and not route.one_way:
        combo = replace(route.base, combo=True)
        return classify_trip(zone, route, history, levels, history.runs_before_current_fares(combo.key), today)
    fares = history.fares(route.key)
    if not fares or history.is_partial(route.key):
        return None
    return classify(route, fares, history.currency(route.key), zone, levels, history.runs_before_current_fares(route.key), today)


def is_stale(history: History, key: str, now: datetime, max_days: float = 3) -> bool:
    seen = history.last_seen(key)
    return seen is None or (now - seen).total_seconds() / 86400 > max_days
