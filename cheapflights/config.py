"""Carga y validación de config.yaml."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from .places import CITY_NAMES
from .search import ONE_WAY, Route

DEFAULT_CONFIG_PATH = Path("config.yaml")
KINDS = ("domestic", "international")
KIND_LABEL = {"domestic": "Colombia", "international": "Internacional"}
DEFAULT_NIGHTS = {"domestic": (2, 5), "international": (6, 14)}
DEFAULT_BAGS = {"domestic": 0, "international": 1}
DEFAULT_ONE_WAY = {"domestic": True, "international": True}
FEEDER_EXTRA_NIGHTS = 2  # la conexión puede salir el día anterior y volver el día siguiente


@dataclass(frozen=True)
class SearchSettings:
    request_delay_seconds: float = 2.0
    max_days_ahead: int = 300
    both_bag_prices: bool = True  # consultar también la otra maleta (alrededor de cada oferta) para mostrar ambos precios
    parallel_requests: int = 3  # peticiones simultáneas a Google dentro de una búsqueda
    requests_per_second: int = 2  # tope global de peticiones por segundo
    rate_limit_wait_seconds: float = 90.0  # si Google bloquea (429), cuánto esperar antes de reintentar
    rate_limit_max_waits: int = 3  # cuántas esperas por corrida antes de rendirse


@dataclass(frozen=True)
class LevelSettings:
    # Etapa 1: comparar con lo que cuesta salir por esas fechas (mediana por día de salida, ±30 días)
    cheap_below_normal: float = 20.0  # 👍 si está 20 % bajo el precio normal
    super_below_normal: float = 45.0  # 🔥 si está 45 % bajo el precio normal…
    super_max_share: float = 3.0  # …y ese precio aparece en máximo el 3 % de las fechas (oferta rara)
    # Etapa 2: comparar con lo que la ruta ha costado en el tiempo
    history_min_days: float = 14
    history_min_runs: int = 20
    super_percentile: float = 10.0
    super_min_discount: float = 20.0
    cheap_percentile: float = 25.0
    cheap_min_discount: float = 10.0


@dataclass(frozen=True)
class AlertSettings:
    repeat_if_drops_percent: float = 5.0
    quiet_hours: tuple[int, int] | None = (22, 6)


@dataclass(frozen=True)
class SummarySettings:
    max_per_section: int = 8
    extra_dates: int = 3
    send_when_empty: bool = True


@dataclass(frozen=True)
class Feeder:
    origin: str
    destination: str

    @property
    def pair(self) -> str:
        return f"{self.origin}-{self.destination}"


@dataclass(frozen=True)
class Zone:
    name: str
    emoji: str
    kind: str  # "domestic" | "international"
    origins: tuple[str, ...]
    destinations: tuple[str, ...]
    months_ahead: int
    nights: tuple[int, int] = (2, 5)  # cuántas noches dura el viaje (mínimo, máximo)
    bags: int = 0  # 1 = el 🔥 se decide con el precio con maleta facturada; 0 = sin maleta
    one_way: bool = False  # buscar también solo ida, en los dos sentidos (avisos 🔥 de solo ida)
    super_price: float | None = None  # precio fijo opcional (toda la zona)
    cheap_price: float | None = None
    prices: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)  # por destino

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()

    def fixed_prices(self, destination: str) -> tuple[float | None, float | None]:
        """(super_barato, barato) fijos para un destino: el del destino o, si no, el de la zona."""
        own = self.prices.get(destination, (None, None))
        return (
            own[0] if own[0] is not None else self.super_price,
            own[1] if own[1] is not None else self.cheap_price,
        )

    def route(self, origin: str, destination: str, bags: int | None = None) -> Route:
        return Route(origin, destination, self.nights, self.bags if bags is None else bags)

    def routes(self) -> list[Route]:
        """Las búsquedas que deciden el 🔥: una por origen y destino, con la maleta de la zona."""
        return [self.route(o, d) for o in self.origins for d in self.destinations if o != d]

    def one_way_routes(self) -> list[Route]:
        """Solo ida en los dos sentidos (origen → destino y destino → origen), con la maleta de la zona."""
        if not self.one_way:
            return []
        out: list[Route] = []
        for o in self.origins:
            for d in self.destinations:
                if o != d:
                    out += [Route(o, d, ONE_WAY, self.bags), Route(d, o, ONE_WAY, self.bags)]
        return out

    def searches(self, both_bag_prices: bool) -> list[Route]:
        """Todo lo que se consulta a Google: la búsqueda que decide y, si se pide, la otra maleta."""
        out: list[Route] = []
        for r in self.routes():
            out.append(r)
            if both_bag_prices:
                out.append(r.other_bags)
        return out


# Colombia no tiene horario de verano: siempre UTC−5.
COLOMBIA_TZ = timezone(timedelta(hours=-5))


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


@dataclass(frozen=True)
class Config:
    home: str = "BGA"
    currency: str = "COP"
    country: str = "CO"
    language: str = "es"
    search: SearchSettings = field(default_factory=SearchSettings)
    levels: LevelSettings = field(default_factory=LevelSettings)
    alerts: AlertSettings = field(default_factory=AlertSettings)
    summary: SummarySettings = field(default_factory=SummarySettings)
    feeders: tuple[Feeder, ...] = ()
    zones: tuple[Zone, ...] = ()
    names: dict[str, str] = field(default_factory=dict)

    def city(self, code: str) -> str:
        return self.names.get(code) or CITY_NAMES.get(code) or code

    def zone(self, name: str) -> Zone:
        wanted = _norm(name)
        for z in self.zones:
            if _norm(z.name) == wanted:
                return z
        raise KeyError(f"No existe la zona '{name}'. Zonas: {', '.join(z.name for z in self.zones)}")

    def zones_of_kind(self, kind: str) -> list[Zone]:
        return [z for z in self.zones if z.kind == kind]

    def zone_for(self, destination: str, kind: str | None = None) -> Zone | None:
        for z in self.zones:
            if destination in z.destinations and (kind is None or z.kind == kind):
                return z
        return None

    # -- conexión desde casa hacia los aeropuertos internacionales ---------------------
    @property
    def feeder_nights(self) -> tuple[int, int]:
        """Noches de la conexión: las del viaje internacional, más margen para salir antes y volver después."""
        intl = self.zones_of_kind("international")
        lo = min((z.nights[0] for z in intl), default=DEFAULT_NIGHTS["international"][0])
        hi = max((z.nights[1] for z in intl), default=DEFAULT_NIGHTS["international"][1])
        return lo, hi + FEEDER_EXTRA_NIGHTS

    @property
    def feeder_months(self) -> int:
        return max((z.months_ahead for z in self.zones_of_kind("international")), default=9)

    def feeder_route(self, hub: str, bags: int) -> Route | None:
        """La búsqueda casa ⇄ hub con la maleta indicada, o None si el hub es casa o no hay conexión."""
        for f in self.feeders:
            if f.origin == self.home and f.destination == hub:
                return Route(f.origin, f.destination, self.feeder_nights, bags)
        return None

    def feeder_searches(self) -> list[Route]:
        """Conexiones a consultar: una por hub y por cada opción de maleta que decida alguna zona internacional."""
        bags = sorted({z.bags for z in self.zones_of_kind("international")})
        return [Route(f.origin, f.destination, self.feeder_nights, b) for f in self.feeders for b in bags]

    @staticmethod
    def local_now(now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        return now.astimezone(COLOMBIA_TZ)

    def local_today(self, now: datetime | None = None) -> date:
        return self.local_now(now).date()


def _iata(code) -> str:
    code = str(code).strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"Código de aeropuerto inválido: {code!r} (deben ser 3 letras, ej. BOG)")
    return code


def _price(value, where: str) -> float:
    try:
        price = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: precio inválido {value!r}") from None
    if price <= 0:
        raise ValueError(f"{where}: el precio debe ser mayor que 0")
    return price


def _price_pair(d: dict, where: str) -> tuple[float | None, float | None]:
    sup = _price(d["super_barato"], f"{where} super_barato") if d.get("super_barato") is not None else None
    cheap = _price(d["barato"], f"{where} barato") if d.get("barato") is not None else None
    if sup is not None and cheap is not None and sup >= cheap:
        raise ValueError(f"{where}: super_barato ({sup:.0f}) debe ser menor que barato ({cheap:.0f})")
    return sup, cheap


def _nights(value, where: str) -> tuple[int, int]:
    """[mín, máx] noches. Un solo número vale como rango de una sola duración."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = [value, value]
    try:
        lo, hi = (int(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: nights debe ser [mínimo, máximo] de noches, ej. [2, 5]") from None
    if lo < 1 or hi < lo or hi > 30:
        raise ValueError(f"{where}: nights debe cumplir 1 ≤ mínimo ≤ máximo ≤ 30 (tienes [{lo}, {hi}])")
    return lo, hi


def _bags(value, where: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if value in (0, 1):
        return int(value)
    if isinstance(value, str) and _norm(value) in ("si", "sí", "true", "con maleta", "con", "1"):
        return 1
    if isinstance(value, str) and _norm(value) in ("no", "false", "sin maleta", "sin", "0"):
        return 0
    raise ValueError(f"{where}: bags debe ser true (con maleta facturada) o false (sin maleta)")


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    search = SearchSettings(**(raw.get("search") or {}))
    known_levels = {f.name for f in fields(LevelSettings)}
    levels = LevelSettings(**{k: v for k, v in (raw.get("levels") or {}).items() if k in known_levels})
    raw_alerts = dict(raw.get("alerts") or {})
    if "quiet_hours" in raw_alerts:
        qh = raw_alerts["quiet_hours"]
        if qh in (None, False, []):
            raw_alerts["quiet_hours"] = None
        else:
            start, end = (int(h) for h in qh)
            if not (0 <= start <= 23 and 0 <= end <= 23):
                raise ValueError("alerts.quiet_hours debe ser [hora_inicio, hora_fin] entre 0 y 23")
            raw_alerts["quiet_hours"] = (start, end)
    alerts = AlertSettings(**raw_alerts)
    summary = SummarySettings(**(raw.get("summary") or {}))

    origins_by_kind = raw.get("origins") or {}
    months_by_kind = raw.get("months_ahead") or {}
    nights_by_kind = {k: _nights(v, f"nights.{k}") for k, v in (raw.get("nights") or {}).items()}
    bags_by_kind = {k: _bags(v, f"bags.{k}") for k, v in (raw.get("bags") or {}).items()}
    one_way_by_kind = {k: _bags(v, f"one_way.{k}") == 1 for k, v in (raw.get("one_way") or {}).items()}
    home = _iata(raw.get("home", "BGA"))
    default_origins = {"domestic": [home], "international": ["BOG", "MDE"]}
    default_months = {"domestic": 6, "international": 9}

    feeders = tuple(
        Feeder(origin=_iata(f["from"]), destination=_iata(f["to"])) for f in (raw.get("feeders") or [])
    )
    for f in feeders:
        if f.origin != home:
            raise ValueError(f"feeders: la conexión {f.pair} debe salir de casa ({home})")
        if f.origin == f.destination:
            raise ValueError(f"feeders: la conexión {f.pair} no tiene sentido")

    names: dict[str, str] = {}
    zones: list[Zone] = []
    for z in raw.get("zones") or []:
        zname = str(z.get("name", "")).strip()
        if not zname:
            raise ValueError("Hay una zona sin nombre en config.yaml")
        kind = z.get("kind", "domestic")
        if kind not in KINDS:
            raise ValueError(f"Zona '{zname}': kind debe ser domestic o international")
        dests_raw = z.get("destinations") or {}
        dests: list[str] = []
        prices: dict[str, tuple[float | None, float | None]] = {}
        items = dests_raw.items() if isinstance(dests_raw, dict) else ((d, None) for d in dests_raw)
        for code, info in items:
            code = _iata(code)
            dests.append(code)
            if isinstance(info, dict):
                city = info.get("ciudad") or info.get("nombre")
                pair = _price_pair(info, f"Zona '{zname}', {code}")
                if pair != (None, None):
                    prices[code] = pair
            else:
                city = info
            if city:
                names[code] = str(city).strip()
        if not dests:
            raise ValueError(f"Zona '{zname}' no tiene destinos")
        super_price, cheap_price = _price_pair(z, f"Zona '{zname}'")
        origins = z.get("origins") or origins_by_kind.get(kind) or default_origins[kind]
        nights = _nights(z["nights"], f"Zona '{zname}'") if z.get("nights") is not None else nights_by_kind.get(kind, DEFAULT_NIGHTS[kind])
        bags = _bags(z["bags"], f"Zona '{zname}'") if z.get("bags") is not None else bags_by_kind.get(kind, DEFAULT_BAGS[kind])
        one_way = (
            _bags(z["one_way"], f"Zona '{zname}' one_way") == 1
            if z.get("one_way") is not None
            else one_way_by_kind.get(kind, DEFAULT_ONE_WAY[kind])
        )
        zones.append(
            Zone(
                name=zname,
                emoji=str(z.get("emoji", "")).strip(),
                kind=kind,
                origins=tuple(_iata(o) for o in origins),
                destinations=tuple(dests),
                months_ahead=int(z.get("months_ahead") or months_by_kind.get(kind) or default_months[kind]),
                nights=nights,
                bags=bags,
                one_way=one_way,
                super_price=super_price,
                cheap_price=cheap_price,
                prices=prices,
            )
        )
    if not zones:
        raise ValueError("config.yaml no define ninguna zona")

    seen_names = [_norm(z.name) for z in zones]
    if len(seen_names) != len(set(seen_names)):
        raise ValueError("Hay zonas con el mismo nombre en config.yaml")
    for kind in KINDS:
        all_dests = [d for z in zones if z.kind == kind for d in z.destinations]
        dupes = sorted({d for d in all_dests if all_dests.count(d) > 1})
        if dupes:
            raise ValueError(f"Destinos repetidos en varias zonas ({kind}): {', '.join(dupes)}")

    intl_origins = {o for z in zones if z.kind == "international" for o in z.origins if o != home}
    missing = sorted(intl_origins - {f.destination for f in feeders})
    if missing:
        raise ValueError(
            f"feeders: falta la conexión desde {home} hacia {', '.join(missing)} "
            "(agrégala para poder sumar el total desde casa)"
        )

    return Config(
        home=home,
        currency=str(raw.get("currency", "COP")).upper(),
        country=str(raw.get("country", "CO")).upper(),
        language=str(raw.get("language", "es")),
        search=search,
        levels=levels,
        alerts=alerts,
        summary=summary,
        feeders=feeders,
        zones=tuple(zones),
        names=names,
    )
