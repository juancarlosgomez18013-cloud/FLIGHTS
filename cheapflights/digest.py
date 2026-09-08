"""Resumen semanal: lo más barato por grupo/continente para planear viajes.

Nivel 1 del "forecast": no predice, muestra el precio real que hoy tiene cada
fecha futura, y de ahí saca el mes y día más baratos por destino.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .config import Config, Group
from .history import History
from .notify import fmt_date, fmt_price

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


@dataclass(frozen=True)
class DealRow:
    origin: str
    destination: str
    price: float
    date: str
    currency: str
    feeder_price: float | None = None  # BGA->origen, si aplica
    feeder_date: str | None = None
    cheapest_month: str | None = None  # "ene 2027"
    cheapest_month_price: float | None = None

    @property
    def total(self) -> float:
        return self.price + (self.feeder_price or 0.0)


def _feeder_cost(history: History, home: str, origin: str, day: str) -> tuple[float | None, str | None]:
    """Precio más barato de home->origin el mismo día o el día anterior."""
    if origin == home:
        return None, None
    cal = history.calendar(f"{home}-{origin}")
    if not cal:
        return None, None
    d = date.fromisoformat(day)
    options = [(cal[k], k) for k in (d.isoformat(), (d - timedelta(days=1)).isoformat()) if k in cal]
    if not options:
        return None, None
    price, when = min(options)
    return price, when


def _cheapest_month(calendar: dict[str, float]) -> tuple[str | None, float | None]:
    by_month: dict[str, float] = defaultdict(lambda: float("inf"))
    for day, price in calendar.items():
        by_month[day[:7]] = min(by_month[day[:7]], price)
    if not by_month:
        return None, None
    month, price = min(by_month.items(), key=lambda kv: kv[1])
    y, m = month.split("-")
    return f"{MESES[int(m) - 1]} {y}", price


def group_deals(config: Config, group: Group, history: History) -> list[DealRow]:
    """Mejor precio por destino dentro del grupo (elige el origen más barato)."""
    best_by_dest: dict[str, DealRow] = {}
    for origin, destination in group.routes():
        cal = history.calendar(f"{origin}-{destination}")
        if not cal:
            continue
        day, price = min(cal.items(), key=lambda kv: (kv[1], kv[0]))
        feeder_price, feeder_date = _feeder_cost(history, config.home, origin, day)
        month, month_price = _cheapest_month(cal)
        row = DealRow(
            origin=origin,
            destination=destination,
            price=price,
            date=day,
            currency=history.route(f"{origin}-{destination}").get("currency", config.currency),
            feeder_price=feeder_price,
            feeder_date=feeder_date,
            cheapest_month=month,
            cheapest_month_price=month_price,
        )
        current = best_by_dest.get(destination)
        if current is None or row.total < current.total:
            best_by_dest[destination] = row
    return sorted(best_by_dest.values(), key=lambda r: r.total)


def format_group_digest(config: Config, group: Group, rows: list[DealRow], top_n: int | None = None) -> str:
    top_n = top_n or config.digest.top_n
    title = f"✈️ *{group.name}* · lo más barato ahora mismo"
    if not rows:
        return title + "\nSin datos todavía. Espera a que corra la búsqueda."
    lines = [title]
    for i, r in enumerate(rows[:top_n], 1):
        line = f"{i}. *{r.destination}* desde {r.origin}: {fmt_price(r.price, r.currency)} el {fmt_date(r.date)}"
        if r.feeder_price is not None:
            line += f"\n   + {config.home}→{r.origin} {fmt_price(r.feeder_price, r.currency)} = *{fmt_price(r.total, r.currency)}* total"
        if r.cheapest_month and r.cheapest_month_price is not None and r.cheapest_month_price != r.price:
            line += f"\n   mes más barato: {r.cheapest_month} ({fmt_price(r.cheapest_month_price, r.currency)})"
        lines.append(line)
    if len(rows) > top_n:
        lines.append(f"…y {len(rows) - top_n} destinos más en data/history.json")
    return "\n".join(lines)


def build_digest(config: Config, history: History, kinds: tuple[str, ...] = ("domestic", "international")) -> list[str]:
    messages: list[str] = []
    for group in config.groups:
        if group.kind not in kinds:
            continue
        rows = group_deals(config, group, history)
        messages.append(format_group_digest(config, group, rows))
    return messages
