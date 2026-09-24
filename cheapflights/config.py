"""Carga y validación de config.yaml."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from .places import CITY_NAMES

DEFAULT_CONFIG_PATH = Path("config.yaml")
KINDS = ("domestic", "international")
KIND_LABEL = {"domestic": "Colombia", "international": "Internacional"}


@dataclass(frozen=True)
class SearchSettings:
    request_delay_seconds: float = 2.0
    max_days_ahead: int = 300


@dataclass(frozen=True)
class LevelSettings:
    # Etapa 1: comparar con las demás fechas de la misma ruta
    cheap_below_normal: float = 20.0  # 👍 si está 20 % bajo el precio normal (mediana de fechas)
    super_below_normal: float = 25.0  # 🔥 si está 25 % bajo el precio normal…
    super_below_cheap_dates: float = 15.0  # …y 15 % bajo el 25 % de fechas más baratas
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
    def route(self) -> str:
        return f"{self.origin}-{self.destination}"


@dataclass(frozen=True)
class Zone:
    name: str
    emoji: str
    kind: str  # "domestic" | "international"
    origins: tuple[str, ...]
    destinations: tuple[str, ...]
    months_ahead: int
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

    def routes(self) -> list[tuple[str, str]]:
        return [(o, d) for o in self.origins for d in self.destinations if o != d]


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


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    search = SearchSettings(**(raw.get("search") or {}))
    levels = LevelSettings(**(raw.get("levels") or {}))
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
    home = _iata(raw.get("home", "BGA"))
    default_origins = {"domestic": [home], "international": ["BOG", "MDE"]}
    default_months = {"domestic": 6, "international": 9}

    feeders = tuple(
        Feeder(origin=_iata(f["from"]), destination=_iata(f["to"])) for f in (raw.get("feeders") or [])
    )

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
        zones.append(
            Zone(
                name=zname,
                emoji=str(z.get("emoji", "")).strip(),
                kind=kind,
                origins=tuple(_iata(o) for o in origins),
                destinations=tuple(dests),
                months_ahead=int(z.get("months_ahead") or months_by_kind.get(kind) or default_months[kind]),
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

    # El tramo desde casa (ej. BGA→BOG) debe buscarse tan lejos como los internacionales,
    # o los totales desde Bucaramanga desaparecen para fechas lejanas.
    intl_months = max((z.months_ahead for z in zones if z.kind == "international"), default=0)
    for f in feeders:
        covering = [z for z in zones if f.origin in z.origins and f.destination in z.destinations]
        if not covering:
            raise ValueError(f"feeders: la ruta {f.route} no está en ninguna zona (agrégala para que se busque)")
        if max(z.months_ahead for z in covering) < intl_months:
            raise ValueError(
                f"feeders: {f.route} se busca {max(z.months_ahead for z in covering)} meses pero los internacionales "
                f"{intl_months}; pon months_ahead: {intl_months} en su zona"
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
