"""Historial de precios en disco (data/history.json), versión 3: ida y vuelta.

Estructura:
  routes["BGA-CTG/2-5n/0m"]:            (clave = Route.key: ruta / noches / maletas)
    origin, destination, nights, bags, currency
    best:     mínimo histórico {price, out, back, seen_at}
    last:     mínimo de la última búsqueda {price, out, back, seen_at}
    runs:     lista acotada de {seen_at, min_price, min_out, min_back, median_price}
    fares:    precio más reciente por viaje: {"ida": [precio por cada nº de noches, o null]}
    partial:  true si solo se buscó una ventana pequeña (la otra opción de maleta, alrededor de la oferta)
  alerts["CTG"]: aviso 🔥 vigente para ese destino (ida y vuelta) {price, out, back, route, at};
  alerts["solo-ida:BGA-CTG"]: igual para un tramo solo ida. Se borra si la oferta desaparece.

Los historiales de versiones anteriores (solo ida) no son comparables y se descartan.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .search import Fares, Route, RouteResult, nights_between

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_PATH = Path("data/history.json")
MAX_RUNS_PER_ROUTE = 200
VERSION = 3


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


def pack_fares(fares: Fares, nights: tuple[int, int]) -> dict[str, list[int | None]]:
    """{(ida, vuelta): precio} → {"ida": [precio con mín noches, …, precio con máx noches]} (compacto en git)."""
    lo, hi = nights
    packed: dict[str, list[int | None]] = {}
    for (out, back), price in fares.items():
        n = nights_between(out, back)
        if not lo <= n <= hi:
            continue
        row = packed.setdefault(out, [None] * (hi - lo + 1))
        row[n - lo] = round(price)
    return dict(sorted(packed.items()))


def unpack_fares(packed: dict[str, list] | None, nights: tuple[int, int]) -> Fares:
    from datetime import date, timedelta

    lo = nights[0]
    fares: Fares = {}
    for out, row in (packed or {}).items():
        d = date.fromisoformat(out)
        for i, price in enumerate(row or []):
            if price:
                fares[(out, (d + timedelta(days=lo + i)).isoformat())] = float(price)
    return fares


class History:
    def __init__(self, data: dict[str, Any] | None = None, path: Path | None = None):
        self.path = path
        if data and int(data.get("version") or 0) < VERSION:
            logger.warning("Historial en formato antiguo (v%s, solo ida): se empieza de cero.", data.get("version"))
            data = None
        self.data: dict[str, Any] = data or {"version": VERSION, "routes": {}, "alerts": {}}
        self.data.setdefault("routes", {})
        self.data.setdefault("alerts", {})
        self.data["version"] = VERSION

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
    def route(self, key: str) -> dict[str, Any]:
        return self.data["routes"].setdefault(key, {"best": None, "last": None, "runs": [], "fares": {}})

    def has_route(self, key: str) -> bool:
        return key in self.data["routes"]

    def routes(self) -> list[str]:
        return sorted(self.data["routes"])

    def keys_for_pair(self, pair: str) -> list[str]:
        """Todas las búsquedas guardadas de un origen-destino, ej. 'BGA-CTG'."""
        return [k for k in self.routes() if k.split("/")[0] == pair]

    def route_of(self, key: str) -> Route | None:
        entry = self.data["routes"].get(key)
        if not entry or "nights" not in entry:
            return None
        return Route(entry["origin"], entry["destination"], tuple(entry["nights"]), int(entry.get("bags", 0)))

    def fares(self, key: str) -> Fares:
        entry = self.data["routes"].get(key)
        if not entry or "nights" not in entry:
            return {}
        return unpack_fares(entry.get("fares"), tuple(entry["nights"]))

    def is_partial(self, key: str) -> bool:
        return bool(self.data["routes"].get(key, {}).get("partial"))

    def runs(self, key: str) -> list[dict[str, Any]]:
        return list(self.data["routes"].get(key, {}).get("runs", []) or [])

    def currency(self, key: str, default: str = "COP") -> str:
        return self.data["routes"].get(key, {}).get("currency", default)

    def best(self, key: str) -> dict[str, Any] | None:
        return self.data["routes"].get(key, {}).get("best")

    def last(self, key: str) -> dict[str, Any] | None:
        return self.data["routes"].get(key, {}).get("last")

    def last_seen(self, key: str) -> datetime | None:
        entry = self.data["routes"].get(key)
        if not entry:
            return None
        if entry.get("last"):
            return parse_ts(entry["last"]["seen_at"])
        if entry.get("fares_at"):
            return parse_ts(entry["fares_at"])
        return None

    def runs_before_current_fares(self, key: str) -> list[dict[str, Any]]:
        """Búsquedas previas a la que produjo los precios guardados (para no compararse consigo misma)."""
        runs = self.runs(key)
        for i in range(len(runs) - 1, -1, -1):
            if runs[i].get("min_price"):
                return runs[:i]
        return runs

    # -- actualización ------------------------------------------------------
    def record(self, result: RouteResult, now: datetime | None = None, partial: bool = False) -> None:
        """Guarda una búsqueda. `partial`: solo una ventana pequeña (no cuenta como corrida completa)."""
        now = now or utcnow()
        route = result.route
        entry = self.route(route.key)
        entry.update(origin=route.origin, destination=route.destination, nights=list(route.nights), bags=route.bags)
        if result.currency:
            entry["currency"] = result.currency
        if partial:
            entry["partial"] = True
            entry["fares"] = pack_fares(result.fares, route.nights)
            entry["fares_at"] = _iso(now)
            return
        entry["partial"] = False
        cheapest = result.cheapest
        if cheapest is None:
            # Sin precios: no tocamos best/last/fares, pero queda constancia.
            entry["runs"].append({"seen_at": _iso(now), "min_price": None, "min_out": None, "min_back": None, "median_price": None})
            entry["runs"] = entry["runs"][-MAX_RUNS_PER_ROUTE:]
            return

        out, back, price = cheapest
        observation = {"price": price, "out": out, "back": back, "seen_at": _iso(now)}
        entry["last"] = observation
        if entry.get("best") is None or price < entry["best"]["price"]:
            entry["best"] = observation
        entry["fares"] = pack_fares(result.fares, route.nights)
        entry["fares_at"] = _iso(now)
        entry["runs"].append(
            {
                "seen_at": _iso(now),
                "min_price": price,
                "min_out": out,
                "min_back": back,
                "median_price": round(statistics.median(result.fares.values())),
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

    def mark_alerted(self, destination: str, price: float, out: str, back: str, route_key: str, now: datetime | None = None) -> None:
        now = now or utcnow()
        self.data["alerts"][destination] = {"price": price, "out": out, "back": back, "route": route_key, "at": _iso(now)}

    def clear_alert(self, destination: str) -> None:
        """La oferta ya no está: si vuelve a aparecer, se avisa de nuevo."""
        self.data["alerts"].pop(destination, None)

    # -- estadística ----------------------------------------------------------
    def price_percentile(self, key: str, price: float) -> float | None:
        """Percentil (empates a mitad) de `price` frente a los mínimos de búsquedas guardadas.

        Necesita al menos 5 búsquedas con precio para decir algo.
        """
        mins = [r["min_price"] for r in self.runs(key) if r.get("min_price")]
        if len(mins) < 5:
            return None
        return midrank_percentile(mins, price)
