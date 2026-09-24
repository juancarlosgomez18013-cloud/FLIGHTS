"""Clasificación de precios: 🔥 súper barato, 👍 barato o nada.

"Precio normal" de una ruta = mediana de sus fechas próximas.

Etapa 1 (poco historial): compara con las demás fechas de la misma ruta.
  👍 si está X % bajo el precio normal.
  🔥 si está Y % bajo el precio normal Y Z % bajo el 25 % de fechas más baratas
     (así la tarifa promo que aparece en muchas fechas no cuenta como 🔥).
Etapa 2 (historial suficiente): compara con lo que la ruta ha costado en el tiempo.
  🔥 si está en el P % más barato de lo visto y al menos D % bajo lo que suele costar.
  👍 igual con umbrales suaves, o si sigue barato frente a sus otras fechas.
En ambas etapas, los precios fijos opcionales de config.yaml también cuentan.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any

from .config import LevelSettings, Zone
from .history import History, midrank_percentile, parse_ts

SUPER = "super"
CHEAP = "barato"
LEVEL_RANK = {SUPER: 0, CHEAP: 1, None: 2}
NEAR_DAYS = 30  # "cerca de esa fecha" = ±30 días


@dataclass(frozen=True)
class Verdict:
    zone: Zone
    origin: str
    destination: str
    price: float
    date: str
    currency: str
    normal: float  # mediana de todas las fechas próximas
    near_normal: float  # mediana de las fechas a ±30 días de la oferta (comparación honesta)
    level: str | None
    stage: int  # 1 = frente a otras fechas, 2 = frente al historial
    cheap_limit: float  # hasta qué precio una fecha cuenta como barata
    percentile: float | None = None
    usual: float | None = None
    tracked_days: float | None = None
    new_low: bool = False
    same_price_dates: tuple[str, ...] = ()  # otras fechas con el mismo precio (±1 %)
    cheap_dates: tuple[tuple[str, float], ...] = ()  # otras fechas baratas (precio distinto), por fecha
    feeder_price: float | None = None
    feeder_date: str | None = None
    feeder_origin: str | None = None
    feeder_estimated: bool = False

    @property
    def route(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def total(self) -> float:
        return self.price + (self.feeder_price or 0.0)

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


def _near_normal(upcoming: dict[str, float], day: str, fallback: float) -> float:
    d = date.fromisoformat(day)
    lo, hi = (d - timedelta(days=NEAR_DAYS)).isoformat(), (d + timedelta(days=NEAR_DAYS)).isoformat()
    near = [p for k, p in upcoming.items() if lo <= k <= hi]
    return statistics.median(near) if len(near) >= 10 else fallback


def classify(
    origin: str,
    destination: str,
    calendar: dict[str, float],
    currency: str,
    zone: Zone,
    levels: LevelSettings,
    past_runs: list[dict[str, Any]],
    today: date,
) -> Verdict | None:
    """Clasifica el mejor precio de una ruta. `past_runs` = búsquedas ANTERIORES a este calendario."""
    # Desde mañana: un vuelo de hoy probablemente ya salió o no se alcanza a tomar.
    upcoming = {d: float(p) for d, p in calendar.items() if d > today.isoformat() and p and p > 0}
    if not upcoming:
        return None
    day, price = min(upcoming.items(), key=lambda kv: (kv[1], kv[0]))
    values = list(upcoming.values())
    normal = statistics.median(values)
    low_quarter = _quantile(values, 0.25)
    fixed_super, fixed_cheap = zone.fixed_prices(destination)

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

    same = tuple(sorted(d for d, p in upcoming.items() if d != day and p <= price * 1.01))
    others = tuple(sorted((d, p) for d, p in upcoming.items() if d != day and price * 1.01 < p <= cheap_limit))

    return Verdict(
        zone=zone,
        origin=origin,
        destination=destination,
        price=price,
        date=day,
        currency=currency,
        normal=normal,
        near_normal=_near_normal(upcoming, day, normal),
        level=level,
        stage=stage,
        cheap_limit=cheap_limit,
        percentile=percentile,
        usual=usual,
        tracked_days=span_days if count >= 2 else None,
        new_low=new_low,
        same_price_dates=same,
        cheap_dates=others,
    )


def feeder_cost(history: History, home: str, origin: str, day: str, today: date) -> tuple[float, str | None, bool] | None:
    """Vuelo home→origin para llegar a tiempo: mismo día o el anterior.

    Devuelve (precio, fecha, estimado). Si no hay precio para esas fechas pero sí para otras,
    usa el precio normal del tramo como estimado para que el total nunca desaparezca.
    """
    if origin == home:
        return None
    cal = {d: float(p) for d, p in history.calendar(f"{home}-{origin}").items() if d > today.isoformat() and p}
    if not cal:
        return None
    d = date.fromisoformat(day)
    options = [(cal[k], k) for k in (d.isoformat(), (d - timedelta(days=1)).isoformat()) if k in cal]
    if options:
        price, when = min(options)
        return price, when, False
    return statistics.median(cal.values()), None, True


def with_feeder(v: Verdict, history: History, home: str, today: date) -> Verdict:
    if v.origin == home:
        return v
    cost = feeder_cost(history, home, v.origin, v.date, today)
    if cost is None:
        return v
    price, when, estimated = cost
    return replace(v, feeder_price=price, feeder_date=when, feeder_origin=home, feeder_estimated=estimated)


def best_per_destination(verdicts: list[Verdict]) -> list[Verdict]:
    """Si un destino sale desde Bogotá y desde Medellín, se queda el más barato en total desde casa."""
    best: dict[str, Verdict] = {}
    for v in verdicts:
        cur = best.get(v.destination)
        key = (v.total, LEVEL_RANK[v.level], v.date)
        if cur is None or key < (cur.total, LEVEL_RANK[cur.level], cur.date):
            best[v.destination] = v
    return list(best.values())


def classify_from_history(zone: Zone, origin: str, destination: str, history: History, levels: LevelSettings, today: date) -> Verdict | None:
    """Clasifica usando el calendario guardado (para el resumen y el plan, sin buscar de nuevo)."""
    route = f"{origin}-{destination}"
    cal = history.calendar(route)
    if not cal:
        return None
    return classify(
        origin, destination, cal, history.currency(route), zone, levels,
        history.runs_before_current_calendar(route), today,
    )


def is_stale(history: History, route: str, now: datetime, max_days: float = 3) -> bool:
    seen = history.last_seen(route)
    return seen is None or (now - seen).total_seconds() / 86400 > max_days
