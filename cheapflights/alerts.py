"""Reglas que deciden cuándo vale la pena avisar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .config import AlertSettings, Group
from .history import History
from .search import RouteResult


@dataclass(frozen=True)
class Alert:
    kind: str  # "target" | "new_low" | "drop"
    group: str
    origin: str
    destination: str
    price: float
    date: str
    currency: str
    previous: float | None = None
    percentile: float | None = None

    @property
    def route(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def key(self) -> str:
        return f"{self.kind}|{self.date}"


def evaluate(
    result: RouteResult,
    previous: dict[str, Any],
    group: Group,
    settings: AlertSettings,
    history: History,
    now: datetime | None = None,
) -> list[Alert]:
    """Compara el resultado de una ruta con su estado previo y devuelve alertas.

    `previous` es lo que devolvió `History.record()` ANTES de guardar esta corrida.
    """
    cheapest = result.cheapest
    if cheapest is None:
        return []
    day, price = cheapest
    prev_best = (previous.get("best") or {}).get("price")
    prev_last = (previous.get("last") or {}).get("price")
    percentile = history.price_percentile(result.route, price)

    candidates: list[Alert] = []
    base = dict(
        group=group.name,
        origin=result.origin,
        destination=result.destination,
        price=price,
        date=day,
        currency=result.currency,
        percentile=percentile,
    )

    if group.target_price is not None and price <= group.target_price:
        candidates.append(Alert(kind="target", previous=group.target_price, **base))

    if settings.new_low and prev_best is not None and price < prev_best:
        candidates.append(Alert(kind="new_low", previous=prev_best, **base))

    if prev_last and prev_last > 0:
        drop = 100 * (prev_last - price) / prev_last
        if drop >= settings.drop_percent:
            candidates.append(Alert(kind="drop", previous=prev_last, **base))

    # Una sola alerta por ruta y corrida: la más "fuerte" gana.
    priority = {"target": 0, "new_low": 1, "drop": 2}
    candidates.sort(key=lambda a: priority[a.kind])
    alerts: list[Alert] = []
    for alert in candidates[:1]:
        if history.was_alerted(alert.route, alert.key, alert.price, settings.cooldown_hours, now):
            continue
        history.mark_alerted(alert.route, alert.key, alert.price, now)
        alerts.append(alert)
    return alerts
