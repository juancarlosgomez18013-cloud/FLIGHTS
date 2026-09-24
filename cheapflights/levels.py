"""Clasificación de precios: 🔥 súper barato, 👍 barato o nada.

Cada "viaje" es una combinación (fecha de ida, fecha de vuelta) dentro del rango de noches
de la zona. "Precio normal" de una ruta = mediana de sus viajes próximos.

Etapa 1 (poco historial): compara con los demás viajes de la misma ruta.
  👍 si está X % bajo el precio normal.
  🔥 si está Y % bajo el precio normal Y Z % bajo el 25 % de viajes más baratos
     (así la tarifa promo que aparece en muchas fechas no cuenta como 🔥).
Etapa 2 (historial suficiente): compara con lo que la ruta ha costado en el tiempo.
  🔥 si está en el P % más barato de lo visto y al menos D % bajo lo que suele costar.
  👍 igual con umbrales suaves, o si sigue barato frente a sus otros viajes.
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
    tracked_days: float | None = None
    new_low: bool = False
    same_price_trips: tuple[tuple[str, str], ...] = ()  # otros viajes al mismo precio (±1 %)
    cheap_trips: tuple[tuple[str, str, float], ...] = ()  # otros viajes baratos (precio distinto), por fecha
    other_bag_price: float | None = None  # el mismo viaje con la otra opción de maleta
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


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))]


def _near_normal(upcoming: Fares, out: str, fallback: float) -> float:
    d = date.fromisoformat(out)
    lo, hi = (d - timedelta(days=NEAR_DAYS)).isoformat(), (d + timedelta(days=NEAR_DAYS)).isoformat()
    near = [p for (o, _), p in upcoming.items() if lo <= o <= hi]
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
    values = list(upcoming.values())
    normal = statistics.median(values)
    low_quarter = _quantile(values, 0.25)
    fixed_super, fixed_cheap = zone.fixed_prices(route.destination)

    cheap_limit = normal * (1 - levels.cheap_below_normal / 100)
    if fixed_cheap is not None:
        cheap_limit = max(cheap_limit, fixed_cheap)
    relative_super = price <= min(
        normal * (1 - levels.super_below_normal / 100),
        low_quarter * (1 - levels.super_below_cheap_dates / 100),
    )
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
        if (percentile <= levels.super_percentile and discount >= levels.super_min_discount) or is_fixed_super:
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
        near_normal=_near_normal(upcoming, out, normal),
        level=level,
        stage=stage,
        cheap_limit=cheap_limit,
        percentile=percentile,
        usual=usual,
        tracked_days=span_days if count >= 2 else None,
        new_low=new_low,
        same_price_trips=same,
        cheap_trips=others,
    )


def other_bag_price(history: History, route: Route, out: str, back: str) -> float | None:
    """Precio del mismo viaje con la otra opción de maleta, si se buscó."""
    return history.fares(route.other_bags.key).get((out, back))


def with_other_bag(v: Verdict, history: History) -> Verdict:
    return replace(v, other_bag_price=other_bag_price(history, v.route, v.out, v.back))


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
    """Completa un veredicto con el precio de la otra maleta y la conexión desde casa."""
    return with_feeder(with_other_bag(v, history), history, config, today)


def best_per_destination(verdicts: list[Verdict]) -> list[Verdict]:
    """Si un destino sale desde Bogotá y desde Medellín, se queda el más barato en total desde casa."""
    best: dict[str, Verdict] = {}
    for v in verdicts:
        cur = best.get(v.destination)
        key = (v.total, LEVEL_RANK[v.level], v.out)
        if cur is None or key < (cur.total, LEVEL_RANK[cur.level], cur.out):
            best[v.destination] = v
    return list(best.values())


def classify_from_history(zone: Zone, route: Route, history: History, levels: LevelSettings, today: date) -> Verdict | None:
    """Clasifica usando los precios guardados (para el resumen y el plan, sin buscar de nuevo)."""
    fares = history.fares(route.key)
    if not fares or history.is_partial(route.key):
        return None
    return classify(route, fares, history.currency(route.key), zone, levels, history.runs_before_current_fares(route.key), today)


def is_stale(history: History, key: str, now: datetime, max_days: float = 3) -> bool:
    seen = history.last_seen(key)
    return seen is None or (now - seen).total_seconds() / 86400 > max_days
