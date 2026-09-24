"""Textos de los mensajes. Todo en español y pensado para leerse en el celular.

Marcado mínimo, que cada canal convierte (ver notify.py):
  *negrita*            → negrita en Telegram y WhatsApp
  [texto](https://…)   → enlace en Telegram; en WhatsApp se agrega la URL debajo
"""

from __future__ import annotations

import urllib.parse
from collections import Counter
from dataclasses import dataclass
from datetime import date

from .config import KINDS, Config
from .festivos import festivos_en
from .levels import CHEAP, LEVEL_RANK, SUPER, Verdict
from .notify import to_plain
from .places import flag
from .search import Fares

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

MAX_VISIBLE_CHARS = 3500  # Telegram permite 4096 caracteres visibles; dejamos margen
FOOTER = "ℹ️ Precio por persona, 1 adulto. Confirma el precio antes de comprar."
KIND_HEADER = {"domestic": "🇨🇴 *COLOMBIA*", "international": "✈️ *INTERNACIONAL*"}
LEVEL_TITLE = {SUPER: "🔥 *Súper barato*", CHEAP: "👍 *Barato*"}
ONE_WAY_TITLE = "🎫 *Solo ida*"
BAGS_TEXT = {0: "sin maleta", 1: "con maleta facturada"}
BAGS_ICON = {0: "🎒", 1: "🧳"}
COMPACT_FROM = 3  # con 3 o más 🔥 a la vez, se manda una lista corta en vez de fichas


# -- formatos básicos ---------------------------------------------------------

def fmt_price(price: float, currency: str = "COP") -> str:
    text = f"{price:,.0f}".replace(",", ".")
    return f"${text}" if currency == "COP" else f"{text} {currency}"


def fmt_approx(price: float, currency: str = "COP") -> str:
    """Precio redondeado a miles: 'unos $124.000'."""
    return "unos " + fmt_price(round(price, -3), currency)


def fmt_date_long(day: str, today: date | None = None) -> str:
    """'2026-10-29' → 'jueves 29 de octubre' (+ año si no es el actual)."""
    d = date.fromisoformat(day)
    text = f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"
    if today and d.year != today.year:
        text += f" de {d.year}"
    return text


def fmt_date_short(day: str, today: date | None = None) -> str:
    """'2026-10-29' → 'jue 29 oct' (+ año si no es el actual)."""
    d = date.fromisoformat(day)
    text = f"{DIAS_CORTOS[d.weekday()]} {d.day} {MESES_CORTOS[d.month - 1]}"
    if today and d.year != today.year:
        text += f" {d.year}"
    return text


def fmt_nights(n: int) -> str:
    return f"{n} noche{'s' if n != 1 else ''}"


def fmt_trip_short(out: str, back: str, today: date | None = None) -> str:
    """'sáb 24 → mié 28 oct' (o 'sáb 28 nov → mié 2 dic'; con año si no es el actual). Solo ida: 'sáb 24 oct'."""
    if out == back:
        return fmt_date_short(out, today)
    o, b = date.fromisoformat(out), date.fromisoformat(back)
    left = f"{DIAS_CORTOS[o.weekday()]} {o.day}"
    if (o.year, o.month) != (b.year, b.month):
        left += f" {MESES_CORTOS[o.month - 1]}"
        if o.year != b.year:
            left += f" {o.year}"
    return f"{left} → {fmt_date_short(back, today)}"


def fmt_trip_long(out: str, back: str, today: date | None = None) -> str:
    """'sábado 24 de octubre → miércoles 28 de octubre · 4 noches' (con año si no es el actual)."""
    o, b = date.fromisoformat(out), date.fromisoformat(back)
    left = fmt_date_long(out, today if o.year != b.year else None)
    return f"{left} → {fmt_date_long(back, today)} · {fmt_nights((b - o).days)}"


def fmt_percent(value: float) -> str:
    return f"{value:.0f} %"


def flights_link(config: Config, origin: str, destination: str, out: str, back: str) -> str:
    """Búsqueda en Google Flights: ida y vuelta, o solo ida si la vuelta es el mismo día de la ida."""
    q = f"Flights from {origin} to {destination} on {out} one way" if out == back else f"Flights from {origin} to {destination} on {out} through {back}"
    return "https://www.google.com/travel/flights?" + urllib.parse.urlencode(
        {"q": q, "curr": config.currency, "hl": config.language, "gl": config.country}
    )


def link(label: str, url: str) -> str:
    return f"[{label}]({url})"


def visible_len(text: str) -> int:
    """Largo como lo cuenta Telegram: texto visible (sin URLs de enlaces) en unidades UTF-16."""
    return len(to_plain(text, keep_bold=False).encode("utf-16-le")) // 2


def destination_icon(v: Verdict) -> str:
    """Bandera del país para internacionales; emoji de la zona para Colombia."""
    return flag(v.destination) or v.zone.emoji


def holiday_text(out: str, back: str, today: date | None = None) -> str | None:
    """'🎉 Puente festivo: lun 2 nov (Todos los Santos)' si el viaje incluye un festivo."""
    found = festivos_en(out, back)
    if not found:
        return None
    puente = any(d.weekday() in (0, 4) for d, _ in found)
    shown = " y ".join(f"{fmt_date_short(d.isoformat(), today)} ({name})" for d, name in found[:2])
    return ("🎉 Puente festivo: " if puente else "🎉 Festivo en el viaje: ") + shown


# -- empaquetado en mensajes -----------------------------------------------------

@dataclass
class Piece:
    """Un pedazo que no se parte. `context` se repite si arranca un mensaje nuevo."""

    text: str
    context: str = ""
    verdicts: tuple[Verdict, ...] = ()


def pack(pieces: list[Piece], limit: int = MAX_VISIBLE_CHARS, footer: str | None = FOOTER) -> list[tuple[str, list[Verdict]]]:
    """Arma mensajes sin partir destinos. Devuelve (texto, veredictos que van en ese mensaje)."""
    messages: list[tuple[str, list[Verdict]]] = []
    lines: list[str] = []
    verdicts: list[Verdict] = []

    def flush():
        nonlocal lines, verdicts
        if lines:
            messages.append(("\n".join(lines), verdicts))
        lines, verdicts = [], []

    for piece in pieces:
        candidate = "\n".join(lines + [piece.text])
        if lines and visible_len(candidate) > limit:
            flush()
            if piece.context:
                lines.append(piece.context)
        lines.append(piece.text)
        verdicts.extend(piece.verdicts)
    flush()
    if footer and messages:
        text, vs = messages[-1]
        if visible_len(text + "\n\n" + footer) <= limit:
            messages[-1] = (text + "\n\n" + footer, vs)
        else:
            messages.append((footer, []))
    return messages


def texts(packed: list[tuple[str, list[Verdict]]]) -> list[str]:
    return [t for t, _ in packed]


# -- detalles compartidos ------------------------------------------------------------

def _other_dates_line(config: Config, v: Verdict, today: date) -> str | None:
    n = config.summary.extra_dates
    outs = v.same_price_outs
    if outs:
        shown = ", ".join(fmt_date_short(d, today) for d in outs[:n])
        more = len(outs)
        return f"📅 Mismo precio saliendo en {more} fecha{'s' if more != 1 else ''} más: {shown}{'…' if more > n else ''}"
    if v.cheap_trips:
        cheapest = sorted(v.cheap_trips, key=lambda t: (t[2], t[0]))[:n]
        shown = " · ".join(f"{fmt_trip_short(o, b, today)} {fmt_price(p, v.currency)}" for o, b, p in sorted(cheapest))
        return f"📅 También barato: {shown}"
    return None


def _savings_text(v: Verdict) -> str | None:
    if v.savings_percent < 10:
        return None
    return f"cerca de esa fecha suele costar {fmt_approx(v.near_normal, v.currency)} (ahorras {fmt_percent(v.savings_percent)})"


def _history_line(v: Verdict) -> str | None:
    if v.stage != 2:
        return None
    if v.new_low and v.tracked_days:
        return f"📉 El precio más bajo en {v.tracked_days:.0f} días de seguimiento"
    if v.percentile is not None:
        if v.percentile < 1:
            return "📉 Casi nunca ha estado así de barato"
        return f"📉 Solo el {fmt_percent(v.percentile)} de las veces ha estado así de barato"
    return None


def _other_bag_text(v: Verdict) -> str | None:
    if v.other_bag_price is None:
        return None
    other = 1 - v.bags
    return f"{BAGS_ICON[other]} {BAGS_TEXT[other][0].upper()}{BAGS_TEXT[other][1:]}: {fmt_price(v.other_bag_price, v.currency)}"


def _split_text(v: Verdict) -> str | None:
    if v.split_price is None:
        return None
    return f"✂️ Armado con dos tramos solo ida: {fmt_price(v.split_price, v.currency)} (ahorras {fmt_price(v.price - v.split_price, v.currency)})"


def _trip_title(config: Config, v: Verdict) -> str:
    if v.one_way:
        return f"{config.city(v.origin)} → {config.city(v.destination)}"
    return f"{config.city(v.origin)} ⇄ {config.city(v.destination)}"


def _feeder_lines(config: Config, v: Verdict, today: date) -> list[str]:
    if v.zone.kind != "international" or v.origin == config.home:
        return []
    home = config.city(v.feeder_origin or config.home)
    hub = config.city(v.origin)
    if v.feeder_price is None:
        return [f"➕ Más el vuelo {home} ⇄ {hub} (aún sin precio)"]
    if v.feeder_estimated:
        return [
            f"➕ {home} ⇄ {hub}: {fmt_approx(v.feeder_price, v.currency)} (aprox.)",
            f"🧾 *Total desde {home}: {fmt_approx(v.total, v.currency)}*",
        ]
    return [
        f"➕ {home} ⇄ {hub}: {fmt_price(v.feeder_price, v.currency)} ({fmt_trip_short(v.feeder_out, v.feeder_back, today)})",
        f"🧾 *Total desde {home}: {fmt_price(v.total, v.currency)}*",
    ]


# -- aviso inmediato 🔥 ---------------------------------------------------------

def format_super_alert(config: Config, v: Verdict, today: date) -> str:
    if v.one_way:
        lines = [
            f"🔥 *SÚPER BARATO · SOLO IDA* · {v.zone.label}",
            f"*{_trip_title(config, v)}*",
            f"💰 *{fmt_price(v.price, v.currency)}* solo ida · {BAGS_TEXT[v.bags]}",
            f"🗓️ {fmt_date_long(v.out, today)}",
        ]
    else:
        lines = [
            f"🔥 *SÚPER BARATO* · {v.zone.label}",
            f"*{_trip_title(config, v)}*",
            f"💰 *{fmt_price(v.price, v.currency)}* ida y vuelta · {BAGS_TEXT[v.bags]}",
        ]
        for extra in (_other_bag_text(v), _split_text(v)):
            if extra:
                lines.append(extra)
        lines.append(f"🗓️ {fmt_trip_long(v.out, v.back, today)}")
    holiday = holiday_text(v.out, v.back, today)
    if holiday:
        lines.append(holiday)
    lines.extend(_feeder_lines(config, v, today))
    savings = _savings_text(v)
    if savings:
        lines.append("📊 " + savings[0].upper() + savings[1:])
    for extra in (_history_line(v), _other_dates_line(config, v, today)):
        if extra:
            lines.append(extra)
    lines.append(link("👉 Ver en Google Flights", flights_link(config, v.origin, v.destination, v.out, v.back)))
    return "\n".join(lines)


def _item(config: Config, v: Verdict, today: date) -> str:
    """Una línea (y detalles cortos) por destino, para listas y el resumen."""
    label = _trip_title(config, v) if v.one_way else config.city(v.destination)
    when = fmt_trip_short(v.out, v.back, today) + ("" if v.one_way else f" ({fmt_nights(v.nights)})")
    icon = destination_icon(v) if v.destination != config.home else flag(v.origin) or v.zone.emoji
    lines = [
        f"• {icon} *{link(label, flights_link(config, v.origin, v.destination, v.out, v.back))}*: "
        f"{fmt_price(v.price, v.currency)} · {when}"
    ]
    details = [("solo ida · " if v.one_way else "") + BAGS_TEXT[v.bags]]
    other = _other_bag_text(v)
    if other:
        details[0] += f" · {other[2:3].lower()}{other[3:]}"
    if v.split_price is not None:
        details.append(f"armado con dos tramos solo ida: {fmt_price(v.split_price, v.currency)}")
    if v.zone.kind == "international":
        via = f"sale de {config.city(v.origin)}"
        if v.feeder_price is not None:
            via += f" · con la conexión desde {config.city(v.feeder_origin or config.home)}: {fmt_approx(v.total, v.currency)}"
        details.append(via)
    holiday = holiday_text(v.out, v.back, today)
    if holiday:
        details.append(holiday[2:].strip()[0].lower() + holiday[2:].strip()[1:])
    savings = _savings_text(v)
    if savings:
        details.append(savings)
    other_dates = _other_dates_line(config, v, today)
    if other_dates:
        details.append(other_dates.removeprefix("📅 ").replace("Mismo precio", "mismo precio").replace("También barato", "también barato"))
    lines.extend(f"   {d}" for d in details)
    return "\n".join(lines)


def format_alerts_packed(config: Config, verdicts: list[Verdict], today: date) -> list[tuple[str, list[Verdict]]]:
    """Avisos 🔥 empaquetados en mensajes, con los veredictos que lleva cada uno."""
    ordered = sorted(verdicts, key=lambda v: (-v.savings_percent, v.total))
    if len(ordered) < COMPACT_FROM:
        return pack([Piece(format_super_alert(config, v, today) + "\n", verdicts=(v,)) for v in ordered])
    n_one_way = sum(1 for v in ordered if v.one_way)
    title = f"🔥 *{len(ordered)} vuelos súper baratos*" if n_one_way else f"🔥 *{len(ordered)} viajes súper baratos*"
    pieces = [Piece(title + "\n")]
    for kind in KINDS:
        items = [v for v in ordered if v.zone.kind == kind]
        if not items:
            continue
        header = f"{KIND_HEADER[kind]} · {_origin_text(config, kind)}"
        pieces.append(Piece(header, context=title + " (sigue)"))
        for v in items:
            pieces.append(Piece(_item(config, v, today), context=f"{header} (sigue)", verdicts=(v,)))
    return pack(pieces)


def format_alerts(config: Config, verdicts: list[Verdict], today: date) -> list[str]:
    return texts(format_alerts_packed(config, verdicts, today))


# -- resumen diario ☀️ -----------------------------------------------------------

def _origin_text(config: Config, kind: str) -> str:
    if kind == "domestic":
        return f"desde {config.city(config.home)}"
    origins = dict.fromkeys(o for z in config.zones_of_kind(kind) for o in z.origins)
    return "desde " + " o ".join(config.city(o) for o in origins)


def _sort_key(v: Verdict):
    return (-v.savings_percent, v.total)


def format_summary(
    config: Config,
    verdicts_by_kind: dict[str, list[Verdict]],
    today: date,
    stale_days_by_kind: dict[str, float | None] | None = None,
) -> list[str]:
    """Resumen diario. `stale_days_by_kind[kind]` = días sin datos nuevos (None si está al día)."""
    stale_days_by_kind = stale_days_by_kind or {}
    limit = config.summary.max_per_section
    pieces = [Piece(f"☀️ *Viajes baratos de hoy* · {fmt_date_long(today.isoformat())}\n")]
    anything = False
    for kind in KINDS:
        if not config.zones_of_kind(kind):
            continue
        header = f"{KIND_HEADER[kind]} · {_origin_text(config, kind)}"
        pieces.append(Piece(header))
        verdicts = verdicts_by_kind.get(kind) or []
        stale = stale_days_by_kind.get(kind)
        if stale is not None:
            pieces.append(Piece(f"⚠️ Hace {stale:.0f} días que no llegan precios nuevos: puede que la búsqueda esté fallando."))
        if not verdicts and stale is None:
            pieces.append(Piece("Aún no hay datos. Llegarán con la próxima búsqueda."))
        round_trips = [v for v in verdicts if not v.one_way]
        for level in (SUPER, CHEAP):
            items = sorted((v for v in round_trips if v.level == level), key=_sort_key)
            if not items:
                continue
            anything = True
            title = LEVEL_TITLE[level]
            pieces.append(Piece(title, context=f"{header} (sigue)"))
            for v in items[:limit]:
                pieces.append(Piece(_item(config, v, today), context=f"{header} (sigue)\n{title}"))
            if len(items) > limit:
                pieces.append(Piece(f"   …y {len(items) - limit} destinos más (salen en el plan del lunes)"))
        one_way = sorted((v for v in verdicts if v.one_way and v.level), key=lambda v: (LEVEL_RANK[v.level], -v.savings_percent, v.price))
        if one_way:
            anything = True
            pieces.append(Piece(ONE_WAY_TITLE, context=f"{header} (sigue)"))
            for v in one_way[:limit]:
                mark = "🔥" if v.level == SUPER else "👍"
                pieces.append(Piece(_item(config, v, today).replace("• ", f"• {mark} ", 1), context=f"{header} (sigue)\n{ONE_WAY_TITLE}"))
            if len(one_way) > limit:
                pieces.append(Piece(f"   …y {len(one_way) - limit} tramos más"))
        if verdicts and not any(v.level for v in verdicts):
            pieces.append(Piece("Nada barato por ahora. Te aviso apenas aparezca algo."))
        pieces.append(Piece(""))
    if not anything and not config.summary.send_when_empty:
        return []
    while pieces and pieces[-1].text == "":
        pieces.pop()
    return texts(pack(pieces))


# -- plan semanal 📅 -------------------------------------------------------------

def best_month(fares: Fares, cheap_limit: float, today: date) -> tuple[str, int] | None:
    """Mes con más fechas de ida baratas (≤ cheap_limit). Ignora el mes actual si le quedan <15 días."""
    days_by_month: dict[str, set[str]] = {}
    for (out, _), p in fares.items():
        if out > today.isoformat() and p and float(p) <= cheap_limit:
            days_by_month.setdefault(out[:7], set()).add(out)
    counts = Counter({m: len(days) for m, days in days_by_month.items()})
    current = today.isoformat()[:7]
    days_left = 31 - today.day
    if days_left < 15:
        counts.pop(current, None)
    if not counts:
        return None
    month, n = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    y, m = (int(x) for x in month.split("-"))
    return MESES[m - 1] + (f" {y}" if y != today.year else ""), n


def format_plan(config: Config, rows_by_kind: dict[str, list[tuple[Verdict, tuple[str, int] | None]]], today: date) -> list[str]:
    """rows = [(destino más barato de la zona, (mes con más fechas baratas, cuántas))]."""
    pieces = [Piece("📅 *Plan de viajes* · lo más barato de los próximos meses, ida y vuelta\n")]
    for kind in KINDS:
        rows = rows_by_kind.get(kind)
        if rows is None:
            continue
        header = f"{KIND_HEADER[kind]} · {_origin_text(config, kind)}"
        pieces.append(Piece(header))
        if not rows:
            pieces.append(Piece("Aún no hay datos."))
        for v, month in rows:
            city = config.city(v.destination)
            place = "" if city == v.zone.name else f"{city} "
            mark = {SUPER: " 🔥", CHEAP: " 👍"}.get(v.level, "")
            lines = [
                f"{v.zone.emoji} *{v.zone.name}*: {place}{fmt_price(v.price, v.currency)} · "
                f"{fmt_trip_short(v.out, v.back, today)} ({fmt_nights(v.nights)}, {BAGS_TEXT[v.bags]}){mark}"
            ]
            if v.zone.kind == "international":
                via = f"   sale de {config.city(v.origin)}"
                if v.feeder_price is not None:
                    via += f" · con la conexión desde {config.city(v.feeder_origin or config.home)}: {fmt_approx(v.total, v.currency)}"
                lines.append(via)
            if month and month[1] >= 3:  # con 1 o 2 fechas no dice nada útil
                lines.append(f"   🗓️ Más fechas baratas en {month[0]} ({month[1]} días de salida)")
            pieces.append(Piece("\n".join(lines), context=f"{header} (sigue)"))
        pieces.append(Piece(""))
    while pieces and pieces[-1].text == "":
        pieces.pop()
    return texts(pack(pieces))


# -- prueba ✅ --------------------------------------------------------------------

def format_test(config: Config, sample: Verdict | None, today: date) -> list[str]:
    intro = (
        "✅ *Prueba: el bot de vuelos funciona*\n"
        "Si ves este mensaje, los avisos te van a llegar aquí.\n\n"
        "Busco viajes de *ida y vuelta*, con y sin maleta facturada. En Colombia también tramos *solo ida*.\n"
        "🔥 *Súper barato* → te escribo apenas lo encuentro (reviso Colombia cada 6 horas e internacional cada mañana).\n"
        "☀️ *Resumen* → todos los días a las 7:30 a. m., con lo 🔥 y lo 👍 barato.\n"
        "📅 *Plan de viajes* → los lunes."
    )
    pieces = [Piece(intro + "\n")]
    if sample:
        pieces.append(Piece("Así se ve un aviso (ejemplo con precios reales guardados):\n"))
        pieces.append(Piece(format_super_alert(config, sample, today)))
    return texts(pack(pieces))
