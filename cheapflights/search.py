"""Búsqueda de precios de ida y vuelta usando Google Flights (vía la librería `fli`).

Solo este módulo habla con Google. El resto del sistema trabaja con `Route` y
`RouteResult`, así que en pruebas se reemplaza por un buscador falso.

Una `Route` es una búsqueda concreta: origen, destino, rango de noches y si el precio
incluye maleta facturada. Google devuelve, en una sola petición, el precio de cada
combinación (fecha de ida, fecha de regreso) dentro del rango de noches.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

Fares = dict[tuple[str, str], float]  # ("YYYY-MM-DD" ida, "YYYY-MM-DD" vuelta) -> precio

# Google devuelve como máximo unas 200 combinaciones (ida, vuelta) por petición; con más,
# responde vacío. Se pide con margen y la ventana de fechas se parte en trozos.
MAX_COMBOS_PER_REQUEST = 180
MAX_DAYS_PER_REQUEST = 61  # límite de fli/Google para una sola duración


def nights_between(out: str, back: str) -> int:
    return (date.fromisoformat(back) - date.fromisoformat(out)).days


def n_durations(nights: tuple[int, int]) -> int:
    return nights[1] - nights[0] + 1


def chunk_days(nights: tuple[int, int]) -> int:
    """Cuántos días de salida caben en una petición para ese rango de noches."""
    return max(1, min(MAX_DAYS_PER_REQUEST, MAX_COMBOS_PER_REQUEST // n_durations(nights)))


def window_around(day: str, nights: tuple[int, int], start: date, end: date) -> tuple[date, date]:
    """Ventana de una sola petición centrada en `day`, sin salirse de [start, end]."""
    span = chunk_days(nights)
    center = date.fromisoformat(day)
    lo = max(start, center - timedelta(days=(span - 1) // 2))
    hi = min(end, lo + timedelta(days=span - 1))
    lo = max(start, hi - timedelta(days=span - 1))
    return lo, hi


ONE_WAY = (0, 0)  # "noches" de un vuelo solo ida: la vuelta es el mismo día de la ida


@dataclass(frozen=True, order=True)
class Route:
    """Una búsqueda: ida y vuelta (o solo ida si nights == (0, 0)), 1 adulto, con o sin maleta facturada."""

    origin: str
    destination: str
    nights: tuple[int, int]  # (mínimo, máximo) de noches; (0, 0) = solo ida
    bags: int = 0  # maletas facturadas incluidas en el precio (0 o 1)
    combo: bool = False  # el mejor viaje: ida y vuelta normal o armado con dos tramos solo ida (no se busca, se calcula)

    @property
    def one_way(self) -> bool:
        return tuple(self.nights) == ONE_WAY

    @property
    def pair(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def key(self) -> str:
        """Identificador en el historial, ej. 'BGA-CTG/2-5n/0m' o 'BGA-CTG/ida/0m'."""
        if self.one_way:
            return f"{self.pair}/ida/{self.bags}m"
        return f"{self.pair}/{self.nights[0]}-{self.nights[1]}n/{self.bags}m" + ("/armado" if self.combo else "")

    @property
    def base(self) -> "Route":
        """La búsqueda de ida y vuelta normal que hay detrás (sin el armado)."""
        return Route(self.origin, self.destination, self.nights, self.bags)

    @property
    def other_bags(self) -> "Route":
        """La misma búsqueda con la otra opción de maleta."""
        return Route(self.origin, self.destination, self.nights, 1 - self.bags)

    @property
    def outbound(self) -> "Route":
        """El tramo solo ida de ida (origen → destino)."""
        return Route(self.origin, self.destination, ONE_WAY, self.bags)

    @property
    def inbound(self) -> "Route":
        """El tramo solo ida de regreso (destino → origen)."""
        return Route(self.destination, self.origin, ONE_WAY, self.bags)

    def __str__(self) -> str:
        return self.key


@dataclass(frozen=True)
class RouteResult:
    """Precio mínimo por combinación (ida, vuelta) para una ruta. En solo ida, vuelta == ida."""

    route: Route
    fares: Fares = field(default_factory=dict)
    currency: str = "COP"

    @property
    def cheapest(self) -> tuple[str, str, float] | None:
        """(ida, vuelta, precio) más barato; None si no hubo precios."""
        if not self.fares:
            return None
        (out, back), price = min(self.fares.items(), key=lambda kv: (kv[1], kv[0]))
        return out, back, price


class Searcher(Protocol):
    def __call__(self, route: Route, from_date: date, to_date: date) -> RouteResult: ...


class RateLimited(RuntimeError):
    """Google respondió con bloqueo o límite de peticiones."""

    partial: list = []


class Backoff:
    """Tras un bloqueo de Google (HTTP 429), espera y reintenta; se rinde tras `max_waits` esperas en la corrida.

    Google levanta el bloqueo en uno o dos minutos si se deja de insistir. Esperar una vez suele
    salvar la corrida completa; si el bloqueo persiste, se aborta para no empeorarlo.
    """

    def __init__(self, seconds: float = 90.0, max_waits: int = 3, sleep: Callable[[float], None] = time.sleep):
        self.seconds, self.max_waits, self.sleep = seconds, max_waits, sleep
        self.waits_done = 0

    def run(self, call: Callable[[], object]):
        while True:
            try:
                return call()
            except RateLimited as exc:
                if self.waits_done >= self.max_waits or self.seconds <= 0:
                    raise
                self.waits_done += 1
                logger.warning("%s. Espera %.0f s y reintenta (%d/%d).", exc, self.seconds, self.waits_done, self.max_waits)
                self.sleep(self.seconds)


def date_window(months_ahead: int, max_days_ahead: int, today: date | None = None) -> tuple[date, date]:
    """Fechas de ida: desde mañana hasta `months_ahead` meses (máx. `max_days_ahead` días)."""
    today = today or date.today()
    start = today + timedelta(days=1)
    days = min(months_ahead * 30, max_days_ahead)
    return start, today + timedelta(days=days)


def google_searcher(
    currency: str,
    country: str,
    language: str,
    parallel_requests: int = 3,
    requests_per_second: int = 2,
    backoff: Backoff | None = None,
) -> Searcher:
    """Crea un buscador real contra Google Flights (calendario de precios de ida y vuelta).

    `parallel_requests`: cuántos trozos de fechas se piden a la vez.
    `requests_per_second`: tope global de peticiones por segundo (fli trae 10; Google bloquea antes).
    `backoff`: qué hacer ante un HTTP 429 (por defecto, esperar 90 s hasta 3 veces por corrida).
    """

    from fli.models import Airport, BagsFilter, DateSearchFilters, FlightSegment, PassengerInfo, TripType
    from fli.search import SearchDates
    from fli.search.client import Client
    from fli.search.exceptions import SearchHTTPError

    backoff = backoff or Backoff()

    try:
        from fli.search._concurrency import configure_concurrency

        configure_concurrency(max(1, int(parallel_requests)))
    except Exception:  # noqa: BLE001 - si cambia fli, seguimos con su paralelismo por defecto
        logger.debug("No se pudo fijar el paralelismo de fli", exc_info=True)

    class RangeFilters(DateSearchFilters):
        """Igual que DateSearchFilters, pero pide a Google un rango de noches [mín, máx].

        `fli` solo contempla una duración fija; Google acepta un rango y devuelve todas las
        combinaciones de ida y vuelta de una vez, así que una petición cubre todo el rango.
        """

        min_nights: int = 1
        max_nights: int = 1

        def format(self) -> list:
            data = super().format()
            if self.trip_type == TripType.ROUND_TRIP:  # en solo ida el último elemento es el rango de fechas
                data[-1] = [self.min_nights, self.max_nights]
            return data

    class RangeSearchDates(SearchDates):
        """Parte la ventana en trozos que quepan en una petición y conserva el rango de noches."""

        MAX_DAYS_PER_SEARCH = 1  # así fli siempre delega en _build_chunk_filters

        def _build_chunk_filters(self, filters, from_date, to_date):
            chunks = []
            current = from_date
            span = chunk_days((filters.min_nights, filters.max_nights))
            while current <= to_date:
                end = min(current + timedelta(days=span - 1), to_date)
                shift = (current - from_date).days
                segments = [
                    FlightSegment(
                        departure_airport=s.departure_airport,
                        arrival_airport=s.arrival_airport,
                        travel_date=(date.fromisoformat(s.travel_date) + timedelta(days=shift)).isoformat(),
                    )
                    for s in filters.flight_segments
                ]
                chunks.append(
                    RangeFilters(
                        trip_type=filters.trip_type,
                        passenger_info=filters.passenger_info,
                        flight_segments=segments,
                        bags=filters.bags,
                        from_date=current.strftime("%Y-%m-%d"),
                        to_date=end.strftime("%Y-%m-%d"),
                        duration=filters.duration,
                        min_nights=filters.min_nights,
                        max_nights=filters.max_nights,
                    )
                )
                current = end + timedelta(days=1)
            return chunks

    client = RangeSearchDates()
    # Cliente propio con un ritmo global más bajo que el de fli, compartido por todos los hilos.
    client.client = Client(calls_per_second=max(1, int(requests_per_second)))

    def call_google(filters) -> list:
        try:
            return client.search(filters, currency=currency, language=language, country=country) or []
        except SearchHTTPError as exc:
            if exc.status_code in (429, 403):
                raise RateLimited(f"Google bloqueó la búsqueda (HTTP {exc.status_code})") from exc
            raise

    def search(route: Route, from_date: date, to_date: date) -> RouteResult:
        lo, hi = route.nights
        origin, destination = Airport[route.origin], Airport[route.destination]
        segments = [
            FlightSegment(departure_airport=[[origin, 0]], arrival_airport=[[destination, 0]], travel_date=from_date.isoformat()),
        ]
        if not route.one_way:
            segments.append(
                FlightSegment(
                    departure_airport=[[destination, 0]],
                    arrival_airport=[[origin, 0]],
                    travel_date=(from_date + timedelta(days=lo)).isoformat(),
                )
            )
        filters = RangeFilters(
            trip_type=TripType.ONE_WAY if route.one_way else TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=segments,
            bags=BagsFilter(checked_bags=route.bags) if route.bags else None,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
            duration=None if route.one_way else lo,
            min_nights=lo,
            max_nights=hi,
        )
        prices = backoff.run(lambda: call_google(filters))
        fares: Fares = {}
        seen_currency = currency
        for p in prices:
            if not p.price or p.price <= 0 or len(p.date) != (1 if route.one_way else 2):
                continue
            out = p.date[0].date().isoformat()
            back = out if route.one_way else p.date[1].date().isoformat()
            if not lo <= nights_between(out, back) <= hi:
                continue
            fares[(out, back)] = min(fares.get((out, back), p.price), float(p.price))
            if p.currency:
                seen_currency = p.currency
        return RouteResult(route=route, fares=fares, currency=seen_currency)

    return search


SearchJob = tuple[Route, date, date]  # (ruta, primera fecha de ida, última fecha de ida)


class QuietBlockGuard:
    """Detecta cuando Google deja de dar precios sin avisar (responde vacío en vez de HTTP 429).

    Si varias búsquedas seguidas vuelven vacías, repite una búsqueda corta que sí dio precios al
    inicio de la corrida (el "testigo"). Si el testigo también sale vacío, es un bloqueo: espera y
    repite las vacías. Si el testigo trae precios, las vacías son rutas sin vuelos de verdad.
    """

    def __init__(self, searcher: "Searcher", streak: int = 4, wait_seconds: float = 90.0, max_waits: int = 3,
                 sleep: Callable[[float], None] = time.sleep):
        self.searcher, self.streak, self.wait_seconds, self.max_waits, self.sleep = searcher, streak, wait_seconds, max_waits, sleep
        self.witness: SearchJob | None = None
        self.waits_done = 0

    def saw_prices(self, job: SearchJob) -> None:
        if self.witness is None:
            route, start, end = job
            self.witness = (route, start, min(end, start + timedelta(days=chunk_days(route.nights) - 1)))

    def blocked(self) -> bool:
        return self.witness is not None and not self.searcher(*self.witness).fares

    def wait(self) -> None:
        if self.waits_done >= self.max_waits or self.wait_seconds <= 0:
            raise RateLimited("Google dejó de dar precios sin avisar (bloqueo silencioso)")
        self.waits_done += 1
        logger.warning("Google dejó de dar precios sin avisar. Espera %.0f s y repite (%d/%d).",
                       self.wait_seconds, self.waits_done, self.max_waits)
        self.sleep(self.wait_seconds)


def search_routes(
    jobs: list[SearchJob],
    searcher: Searcher,
    delay_seconds: float = 0.0,
    on_error: Callable[[str, Exception], None] | None = None,
    guard: QuietBlockGuard | None = None,
) -> list[RouteResult]:
    """Busca varias rutas en serie, con pausa entre ellas.

    Un error en una ruta no detiene las demás, salvo `RateLimited`, que sí aborta
    porque insistir solo empeora el bloqueo. Con `guard`, un bloqueo silencioso de Google
    (respuestas vacías) se detecta, se espera y se repiten las búsquedas vacías.
    """
    results: list[RouteResult] = []
    empties: list[tuple[int, SearchJob]] = []  # vacías seguidas (posición en results, búsqueda)
    for i, job in enumerate(jobs):
        route, from_date, to_date = job
        if i and delay_seconds:
            time.sleep(delay_seconds)
        try:
            result = searcher(route, from_date, to_date)
            results.append(result)
            if guard is None:
                continue
            if result.fares:
                guard.saw_prices(job)
                empties.clear()
                continue
            empties.append((len(results) - 1, job))
            if len(empties) >= guard.streak and guard.blocked():
                guard.wait()
                for pos, again in empties:
                    results[pos] = searcher(*again)
                if guard.blocked():
                    raise RateLimited("Google sigue sin dar precios después de esperar (bloqueo silencioso)")
                empties.clear()
        except RateLimited as exc:
            exc.partial = results  # lo ya buscado no se pierde
            raise
        except Exception as exc:  # noqa: BLE001 - una ruta rota no debe tumbar la corrida
            logger.warning("Ruta %s falló: %s", route, exc)
            if on_error:
                on_error(route.key, exc)
    return results
