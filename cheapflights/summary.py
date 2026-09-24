"""Arma los datos del resumen diario, el plan semanal y el mensaje de prueba desde el historial."""

from __future__ import annotations

from datetime import datetime

from .config import KINDS, Config
from .history import History
from .levels import LEVEL_RANK, Verdict, best_per_destination, classify_from_history, is_stale, with_feeder
from .messages import best_month

STALE_DAYS = 3


def verdicts_for_kind(config: Config, history: History, kind: str, now: datetime) -> tuple[list[Verdict], float | None]:
    """Mejor veredicto por destino de un tipo (nacional/internacional) y días sin datos nuevos.

    Ignora rutas sin búsquedas recientes para no anunciar precios viejos.
    """
    today = config.local_today(now)
    found: list[Verdict] = []
    newest = None
    for zone in config.zones_of_kind(kind):
        for origin, destination in zone.routes():
            route = f"{origin}-{destination}"
            seen = history.last_seen(route)
            if seen and (newest is None or seen > newest):
                newest = seen
            if is_stale(history, route, now, STALE_DAYS):
                continue
            v = classify_from_history(zone, origin, destination, history, config.levels, today)
            if v:
                found.append(with_feeder(v, history, config.home, today))
    stale_days = None
    if newest is not None and not found:
        stale_days = (now - newest).total_seconds() / 86400
    return best_per_destination(found), stale_days


def summary_data(config: Config, history: History, now: datetime) -> tuple[dict[str, list[Verdict]], dict[str, float | None]]:
    by_kind: dict[str, list[Verdict]] = {}
    stale: dict[str, float | None] = {}
    for kind in KINDS:
        by_kind[kind], stale[kind] = verdicts_for_kind(config, history, kind, now)
    return by_kind, stale


def plan_rows(config: Config, history: History, now: datetime) -> dict[str, list[tuple[Verdict, tuple[str, float] | None]]]:
    """Por cada zona: el destino más barato (total desde casa) y su mes más barato en general."""
    today = config.local_today(now)
    rows: dict[str, list] = {}
    for kind in KINDS:
        zones = config.zones_of_kind(kind)
        if not zones:
            continue
        rows[kind] = []
        for zone in zones:
            candidates = []
            for origin, destination in zone.routes():
                if is_stale(history, f"{origin}-{destination}", now, STALE_DAYS * 3):
                    continue
                v = classify_from_history(zone, origin, destination, history, config.levels, today)
                if v:
                    candidates.append(with_feeder(v, history, config.home, today))
            if not candidates:
                continue
            best = min(candidates, key=lambda v: (v.total, LEVEL_RANK[v.level], v.date))
            month = best_month(history.calendar(best.route), best.cheap_limit, today)
            rows[kind].append((best, month))
    return rows


def sample_verdict(config: Config, history: History, now: datetime) -> Verdict | None:
    """Un ejemplo real para el mensaje de prueba: el mayor ahorro disponible."""
    by_kind, _ = summary_data(config, history, now)
    all_v = [v for vs in by_kind.values() for v in vs]
    if not all_v:
        return None
    return max(all_v, key=lambda v: (v.level is not None, v.savings_percent))
