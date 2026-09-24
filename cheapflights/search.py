"""Búsqueda de precios por fecha usando Google Flights (vía la librería `fli`).

Solo este módulo habla con Google. El resto del sistema trabaja con
`RouteResult`, así que en pruebas se reemplaza por un buscador falso.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteResult:
    """Precio mínimo por día para una ruta (solo ida, 1 adulto)."""

    origin: str
    destination: str
    calendar: dict[str, float] = field(default_factory=dict)  # "YYYY-MM-DD" -> precio
    currency: str = "COP"

    @property
    def route(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def cheapest(self) -> tuple[str, float] | None:
        if not self.calendar:
            return None
        day, price = min(self.calendar.items(), key=lambda kv: (kv[1], kv[0]))
        return day, price


class Searcher(Protocol):
    def __call__(self, origin: str, destination: str, from_date: date, to_date: date) -> RouteResult: ...


class RateLimited(RuntimeError):
    """Google respondió con bloqueo o límite de peticiones."""

    partial: list = []


def date_window(months_ahead: int, max_days_ahead: int, today: date | None = None) -> tuple[date, date]:
    """Desde mañana hasta `months_ahead` meses (máx. `max_days_ahead` días)."""
    today = today or date.today()
    start = today + timedelta(days=1)
    days = min(months_ahead * 30, max_days_ahead)
    return start, today + timedelta(days=days)


def google_searcher(currency: str, country: str, language: str) -> Searcher:
    """Crea un buscador real contra Google Flights."""

    from fli.core.builders import build_date_search_segments
    from fli.models import Airport, DateSearchFilters, PassengerInfo
    from fli.search import SearchDates
    from fli.search.exceptions import SearchHTTPError

    client = SearchDates()

    def search(origin: str, destination: str, from_date: date, to_date: date) -> RouteResult:
        segments, trip_type = build_date_search_segments(
            Airport[origin], Airport[destination], from_date.isoformat()
        )
        filters = DateSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=segments,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
        )
        try:
            prices = client.search(filters, currency=currency, language=language, country=country)
        except SearchHTTPError as exc:
            if exc.status_code in (429, 403):
                raise RateLimited(f"Google bloqueó la búsqueda (HTTP {exc.status_code})") from exc
            raise
        calendar: dict[str, float] = {}
        seen_currency = currency
        for p in prices or []:
            day = p.date[0].date().isoformat()
            if p.price and p.price > 0:
                calendar[day] = min(calendar.get(day, p.price), float(p.price))
            if p.currency:
                seen_currency = p.currency
        return RouteResult(origin=origin, destination=destination, calendar=calendar, currency=seen_currency)

    return search


def search_routes(
    routes: list[tuple[str, str]],
    searcher: Searcher,
    from_date: date,
    to_date: date,
    delay_seconds: float = 0.0,
    on_error: Callable[[str, Exception], None] | None = None,
) -> list[RouteResult]:
    """Busca varias rutas en serie, con pausa entre ellas.

    Un error en una ruta no detiene las demás, salvo `RateLimited`, que sí aborta
    porque insistir solo empeora el bloqueo.
    """
    results: list[RouteResult] = []
    for i, (origin, destination) in enumerate(routes):
        if i and delay_seconds:
            time.sleep(delay_seconds)
        try:
            results.append(searcher(origin, destination, from_date, to_date))
        except RateLimited as exc:
            exc.partial = results  # lo ya buscado no se pierde
            raise
        except Exception as exc:  # noqa: BLE001 - una ruta rota no debe tumbar la corrida
            logger.warning("Ruta %s-%s falló: %s", origin, destination, exc)
            if on_error:
                on_error(f"{origin}-{destination}", exc)
    return results
