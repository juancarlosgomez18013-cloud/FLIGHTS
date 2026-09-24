"""Historial de precios en disco (data/history.json).

Estructura:
  routes["BGA-BOG"]:
    best:     mínimo histórico {price, date, seen_at}
    last:     mínimo de la última búsqueda {price, date, seen_at}
    runs:     lista acotada de {seen_at, min_price, min_date, median_price}
    calendar: precio más reciente por fecha de vuelo {"YYYY-MM-DD": precio}
    currency
  alerts["BOG"]: aviso 🔥 vigente para ese destino {price, date, route, at}; se borra si la oferta desaparece
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
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_ts(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def midrank_percentile(values: list[float], price: float) -> float | None:
    """Qué porcentaje de `values` es más barato que `price` (los empates cuentan la mitad).

    0 = nunca se vio tan barato; 50 = precio normal; 100 = siempre estuvo más barato.
    Con empates a mitad, una ruta de precio plano da 50 (normal), no 0.
    """
    if not values:
        return None
    below = sum(1 for v in values if v < price)
    equal = sum(1 for v in values if v == price)
    return round(100 * (below + 0.5 * equal) / len(values), 1)


class History:
    def __init__(self, data: dict[str, Any] | None = None, path: Path | None = None):
        self.path = path
        self.data: dict[str, Any] = data or {"version": 2, "routes": {}}
        self.data.setdefault("routes", {})
        self.data.setdefault("alerts", {})
        self.data["version"] = 2

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
        # Compacto: este archivo se guarda en git en cada búsqueda.
        path.write_text(
            json.dumps(self.data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # -- consultas ----------------------------------------------------------
    def route(self, route: str) -> dict[str, Any]:
        entry = self.data["routes"].setdefault(
            route, {"best": None, "last": None, "runs": [], "calendar": {}}
        )
        entry.pop("alerted", None)  # formato viejo (v1): ya no se usa
        return entry

    def has_route(self, route: str) -> bool:
        return route in self.data["routes"]

    def calendar(self, route: str) -> dict[str, float]:
        return self.data["routes"].get(route, {}).get("calendar", {}) or {}

    def runs(self, route: str) -> list[dict[str, Any]]:
        return list(self.data["routes"].get(route, {}).get("runs", []) or [])

    def currency(self, route: str, default: str = "COP") -> str:
        return self.data["routes"].get(route, {}).get("currency", default)

    def best(self, route: str) -> dict[str, Any] | None:
        return self.data["routes"].get(route, {}).get("best")

    def last(self, route: str) -> dict[str, Any] | None:
        return self.data["routes"].get(route, {}).get("last")

    def last_seen(self, route: str) -> datetime | None:
        last = self.last(route)
        return parse_ts(last["seen_at"]) if last else None

    def routes(self) -> list[str]:
        return sorted(self.data["routes"])

    def runs_before_current_calendar(self, route: str) -> list[dict[str, Any]]:
        """Búsquedas previas a la que produjo el calendario guardado (para no compararse consigo misma)."""
        runs = self.runs(route)
        for i in range(len(runs) - 1, -1, -1):
            if runs[i].get("min_price"):
                return runs[:i]
        return runs

    # -- actualización ------------------------------------------------------
    def record(self, result: RouteResult, now: datetime | None = None) -> None:
        now = now or utcnow()
        entry = self.route(result.route)
        cheapest = result.cheapest
        if cheapest is None:
            # Sin precios: no tocamos best/last/calendar, pero queda constancia.
            entry["runs"].append({"seen_at": _iso(now), "min_price": None, "min_date": None, "median_price": None})
            entry["runs"] = entry["runs"][-MAX_RUNS_PER_ROUTE:]
            return

        day, price = cheapest
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
                "median_price": round(statistics.median(result.calendar.values())),
            }
        )
        entry["runs"] = entry["runs"][-MAX_RUNS_PER_ROUTE:]

    # -- avisos inmediatos: no repetir ---------------------------------------
    def should_alert(self, destination: str, price: float, repeat_if_drops_percent: float) -> bool:
        """True si hay que avisar: nunca se avisó (o la oferta desapareció) o bajó otro X %."""
        prev = self.data["alerts"].get(destination)
        if not prev:
            return True
        return price <= prev["price"] * (1 - repeat_if_drops_percent / 100)

    def mark_alerted(self, destination: str, price: float, day: str, route: str, now: datetime | None = None) -> None:
        now = now or utcnow()
        self.data["alerts"][destination] = {"price": price, "date": day, "route": route, "at": _iso(now)}

    def clear_alert(self, destination: str) -> None:
        """La oferta ya no está: si vuelve a aparecer, se avisa de nuevo."""
        self.data["alerts"].pop(destination, None)

    # -- estadística ----------------------------------------------------------
    def price_percentile(self, route: str, price: float) -> float | None:
        """Percentil (empates a mitad) de `price` frente a los mínimos de búsquedas guardadas.

        Necesita al menos 5 búsquedas con precio para decir algo.
        """
        mins = [r["min_price"] for r in self.route(route)["runs"] if r.get("min_price")]
        if len(mins) < 5:
            return None
        return midrank_percentile(mins, price)
