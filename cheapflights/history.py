"""Historial de precios en disco (data/history.json).

Estructura por ruta ("BGA-BOG"):
  best:     mínimo histórico {price, date, seen_at}
  last:     mínimo de la última corrida {price, date, seen_at}
  runs:     lista (acotada) de {seen_at, min_price, min_date, median_price}
  calendar: precio más reciente por fecha de vuelo {"YYYY-MM-DD": precio}
  alerted:  {clave_de_alerta: {price, at}} para no repetir avisos
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .search import RouteResult

DEFAULT_HISTORY_PATH = Path("data/history.json")
MAX_RUNS_PER_ROUTE = 200


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


class History:
    def __init__(self, data: dict[str, Any] | None = None, path: Path | None = None):
        self.path = path
        self.data: dict[str, Any] = data or {"version": 1, "routes": {}}
        self.data.setdefault("routes", {})

    # -- persistencia -------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str = DEFAULT_HISTORY_PATH) -> "History":
        path = Path(path)
        if path.exists() and path.stat().st_size > 0:
            return cls(json.loads(path.read_text(encoding="utf-8")), path)
        return cls(path=path)

    def save(self, path: Path | str | None = None) -> None:
        path = Path(path or self.path or DEFAULT_HISTORY_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = _iso(utcnow())
        # Compacto: este archivo se versiona en git en cada corrida.
        path.write_text(json.dumps(self.data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")

    # -- consultas ----------------------------------------------------------
    def route(self, route: str) -> dict[str, Any]:
        return self.data["routes"].setdefault(
            route, {"best": None, "last": None, "runs": [], "calendar": {}, "alerted": {}}
        )

    def has_route(self, route: str) -> bool:
        return route in self.data["routes"]

    def calendar(self, route: str) -> dict[str, float]:
        return self.data["routes"].get(route, {}).get("calendar", {}) or {}

    def best(self, route: str) -> dict[str, Any] | None:
        return self.data["routes"].get(route, {}).get("best")

    def last(self, route: str) -> dict[str, Any] | None:
        return self.data["routes"].get(route, {}).get("last")

    def routes(self) -> list[str]:
        return sorted(self.data["routes"])

    # -- actualización ------------------------------------------------------
    def record(self, result: RouteResult, now: datetime | None = None) -> dict[str, Any]:
        """Guarda una corrida y devuelve el estado PREVIO de la ruta (para comparar)."""
        now = now or utcnow()
        entry = self.route(result.route)
        previous = {"best": entry.get("best"), "last": entry.get("last"), "runs": len(entry["runs"])}

        cheapest = result.cheapest
        if cheapest is None:
            # Sin precios: no tocamos best/last, pero dejamos constancia de la corrida.
            entry["runs"].append({"seen_at": _iso(now), "min_price": None, "min_date": None, "median_price": None})
            entry["runs"] = entry["runs"][-MAX_RUNS_PER_ROUTE:]
            return previous

        day, price = cheapest
        prices = sorted(result.calendar.values())
        observation = {"price": price, "date": day, "seen_at": _iso(now)}
        entry["last"] = observation
        if entry.get("best") is None or price < entry["best"]["price"]:
            entry["best"] = observation
        entry["calendar"] = {d: round(p) for d, p in sorted(result.calendar.items())}
        entry["currency"] = result.currency
        entry["runs"].append(
            {
                "seen_at": _iso(now),
                "min_price": price,
                "min_date": day,
                "median_price": round(statistics.median(prices)),
            }
        )
        entry["runs"] = entry["runs"][-MAX_RUNS_PER_ROUTE:]
        return previous

    # -- control de avisos repetidos -----------------------------------------
    def was_alerted(self, route: str, key: str, price: float, cooldown_hours: int, now: datetime | None = None) -> bool:
        now = now or utcnow()
        alerted = self.route(route).setdefault("alerted", {})
        prev = alerted.get(key)
        if not prev:
            return False
        at = datetime.fromisoformat(prev["at"])
        hours = (now - at).total_seconds() / 3600
        # Se repite solo si pasó el cooldown o si el precio bajó otro 5 %.
        return hours < cooldown_hours and price > prev["price"] * 0.95

    def mark_alerted(self, route: str, key: str, price: float, now: datetime | None = None) -> None:
        now = now or utcnow()
        alerted = self.route(route).setdefault("alerted", {})
        alerted[key] = {"price": price, "at": _iso(now)}
        # Limpieza: no acumular más de 60 claves por ruta.
        if len(alerted) > 60:
            for k in sorted(alerted, key=lambda k: alerted[k]["at"])[: len(alerted) - 60]:
                del alerted[k]

    # -- estadística simple (nivel 2 del forecast) ---------------------------
    def price_percentile(self, route: str, price: float) -> float | None:
        """Qué porcentaje de las corridas previas tuvieron un mínimo MENOR a `price`.

        0 = nunca se vio tan barato; 100 = siempre ha estado más barato.
        Necesita al menos 5 corridas para decir algo.
        """
        mins = [r["min_price"] for r in self.route(route)["runs"] if r.get("min_price")]
        if len(mins) < 5:
            return None
        below = sum(1 for m in mins if m < price)
        return round(100 * below / len(mins), 1)
