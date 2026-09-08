"""Carga y validación de config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass(frozen=True)
class SearchSettings:
    request_delay_seconds: float = 2.0
    max_days_ahead: int = 300


@dataclass(frozen=True)
class AlertSettings:
    drop_percent: float = 15.0
    new_low: bool = True
    cooldown_hours: int = 24


@dataclass(frozen=True)
class DigestSettings:
    top_n: int = 6


@dataclass(frozen=True)
class Feeder:
    origin: str
    destination: str

    @property
    def route(self) -> str:
        return f"{self.origin}-{self.destination}"


@dataclass(frozen=True)
class Group:
    name: str
    kind: str  # "domestic" | "international"
    origins: tuple[str, ...]
    destinations: tuple[str, ...]
    months_ahead: int = 6
    target_price: float | None = None

    def routes(self) -> list[tuple[str, str]]:
        return [(o, d) for o in self.origins for d in self.destinations if o != d]


@dataclass(frozen=True)
class Config:
    currency: str = "COP"
    country: str = "CO"
    language: str = "es"
    home: str = "BGA"
    search: SearchSettings = field(default_factory=SearchSettings)
    alerts: AlertSettings = field(default_factory=AlertSettings)
    digest: DigestSettings = field(default_factory=DigestSettings)
    feeders: tuple[Feeder, ...] = ()
    groups: tuple[Group, ...] = ()

    def group(self, name: str) -> Group:
        for g in self.groups:
            if g.name.lower() == name.lower():
                return g
        raise KeyError(f"No existe el grupo '{name}'. Grupos: {[g.name for g in self.groups]}")

    def groups_of_kind(self, kind: str) -> list[Group]:
        return [g for g in self.groups if g.kind == kind]


def _iata(code: str) -> str:
    code = str(code).strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"Código IATA inválido: {code!r}")
    return code


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    search = SearchSettings(**(raw.get("search") or {}))
    alerts = AlertSettings(**(raw.get("alerts") or {}))
    digest = DigestSettings(**(raw.get("digest") or {}))

    feeders = tuple(
        Feeder(origin=_iata(f["from"]), destination=_iata(f["to"]))
        for f in (raw.get("feeders") or [])
    )

    groups: list[Group] = []
    for g in raw.get("groups") or []:
        kind = g.get("kind", "domestic")
        if kind not in ("domestic", "international"):
            raise ValueError(f"Grupo {g.get('name')}: kind debe ser domestic o international")
        groups.append(
            Group(
                name=str(g["name"]),
                kind=kind,
                origins=tuple(_iata(o) for o in g.get("origins") or [raw.get("home", "BGA")]),
                destinations=tuple(_iata(d) for d in g.get("destinations") or []),
                months_ahead=int(g.get("months_ahead", 6)),
                target_price=float(g["target_price"]) if g.get("target_price") is not None else None,
            )
        )
    if not groups:
        raise ValueError("config.yaml no define ningún grupo de rutas")

    names = [g.name.lower() for g in groups]
    if len(names) != len(set(names)):
        raise ValueError("Hay grupos con el mismo nombre en config.yaml")

    return Config(
        currency=str(raw.get("currency", "COP")).upper(),
        country=str(raw.get("country", "CO")).upper(),
        language=str(raw.get("language", "es")),
        home=_iata(raw.get("home", "BGA")),
        search=search,
        alerts=alerts,
        digest=digest,
        feeders=feeders,
        groups=tuple(groups),
    )
