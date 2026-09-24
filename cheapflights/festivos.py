"""Festivos de Colombia, para marcar los viajes que caen en puente.

Se calculan (no hay lista fija): los de fecha fija, los que la Ley Emiliani traslada al
lunes siguiente y los que dependen de la Semana Santa.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

FIJOS = {
    (1, 1): "Año Nuevo",
    (5, 1): "Día del Trabajo",
    (7, 20): "Independencia",
    (8, 7): "Batalla de Boyacá",
    (12, 8): "Inmaculada Concepción",
    (12, 25): "Navidad",
}
# Se trasladan al lunes siguiente si no caen en lunes (Ley Emiliani)
AL_LUNES = {
    (1, 6): "Reyes Magos",
    (3, 19): "San José",
    (6, 29): "San Pedro y San Pablo",
    (8, 15): "Asunción de la Virgen",
    (10, 12): "Día de la Raza",
    (11, 1): "Todos los Santos",
    (11, 11): "Independencia de Cartagena",
}
# Días después del Domingo de Pascua (los tres últimos ya trasladados al lunes)
DESDE_PASCUA = {
    -3: "Jueves Santo",
    -2: "Viernes Santo",
    43: "Ascensión del Señor",
    64: "Corpus Christi",
    71: "Sagrado Corazón",
}


def pascua(year: int) -> date:
    """Domingo de Pascua (algoritmo de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _siguiente_lunes(d: date) -> date:
    return d if d.weekday() == 0 else d + timedelta(days=7 - d.weekday())


@lru_cache(maxsize=None)
def festivos(year: int) -> dict[date, str]:
    """Festivos del año: fecha -> nombre."""
    out: dict[date, str] = {}
    for (m, d), name in FIJOS.items():
        out[date(year, m, d)] = name
    for (m, d), name in AL_LUNES.items():
        out[_siguiente_lunes(date(year, m, d))] = name
    p = pascua(year)
    for offset, name in DESDE_PASCUA.items():
        out[p + timedelta(days=offset)] = name
    return dict(sorted(out.items()))


def es_festivo(d: date) -> bool:
    return d in festivos(d.year)


def festivos_en(out: str, back: str) -> list[tuple[date, str]]:
    """Festivos entre la ida y la vuelta (ambas incluidas)."""
    start, end = date.fromisoformat(out), date.fromisoformat(back)
    found: list[tuple[date, str]] = []
    for year in range(start.year, end.year + 1):
        found.extend((d, n) for d, n in festivos(year).items() if start <= d <= end)
    return found


def es_puente(out: str, back: str) -> bool:
    """True si el viaje incluye un festivo pegado a un fin de semana (lunes o viernes)."""
    return any(d.weekday() in (0, 4) for d, _ in festivos_en(out, back))
