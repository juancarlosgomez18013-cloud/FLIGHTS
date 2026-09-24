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
FOOTER = "ℹ️ Confirma el precio en el enlace antes de comprar."
KIND_HEADER = {"domestic": "🇨🇴 *COLOMBIA*", "international": "✈️ *INTERNACIONAL*"}
LEVEL_TITLE = {SUPER: "🔥 *Súper baratos*", CHEAP: "👍 *Baratos*"}
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


def fmt_range(out: str, back: str, today: date | None = None) -> str:
    """Fechas compactas: '1–7 nov', '28 nov–2 dic', '14 oct' (solo ida); con año si no es el actual."""
    o, b = date.fromisoformat(out), date.fromisoformat(back)
    year = lambda d: f" {d.year}" if today and d.year != today.year else ""  # noqa: E731
    if out == back:
        return f"{o.day} {MESES_CORTOS[o.month - 1]}{year(o)}"
    if (o.year, o.month) == (b.year, b.month):
        return f"{o.day}–{b.day} {MESES_CORTOS[b.month - 1]}{year(b)}"
    left = f"{o.day} {MESES_CORTOS[o.month - 1]}" + (f" {o.year}" if o.year != b.year else "")
    return f"{left}–{b.day} {MESES_CORTOS[b.month - 1]}{year(b) if o.year == b.year else f' {b.year}'}"


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
        text = text.rstrip()
        if visible_len(text + "\n\n" + footer) <= limit:
            messages[-1] = (text + "\n\n" + footer, vs)
        else:
            messages.append((footer, []))
    return messages


def texts(packed: list[tuple[str, list[Verdict]]]) -> list[str]:
    return [t for t, _ in packed]


# -- piezas compartidas -----------------------------------------------------------

def _title(config: Config, v: Verdict) -> str:
    """'San Andrés', 'Madrid, España' o, en solo ida, 'Bogotá → Bucaramanga'."""
    if v.one_way:
        return f"{config.city(v.origin)} → {config.city(v.destination)}"
    return config.city(v.destination)


def _icon(v: Verdict) -> str:
    return "🎫" if v.one_way else (flag(v.destination) or v.zone.emoji)


def _link(config: Config, v: Verdict) -> str:
    return flights_link(config, v.origin, v.destination, v.out, v.back)


def _normally(v: Verdict) -> str | None:
    if v.savings_percent < 10:
        return None
    return f"Normalmente {fmt_approx(v.near_normal, v.currency)[5:]} · ahorras {fmt_percent(v.savings_percent)}"


def _bags_line(v: Verdict) -> str:
    """'🎒 Sin maleta · con maleta: $692.900' o '🧳 Con maleta · sin maleta: $1.900.000'."""
    text = "🧳 Con maleta" if v.bags else "🎒 Sin maleta"
    if v.other_bag_price is not None:
        text += f" · {BAGS_TEXT[1 - v.bags].split(' facturada')[0]}: {fmt_price(v.other_bag_price, v.currency)}"
    return text


def _holiday_short(v: Verdict, today: date) -> str | None:
    found = festivos_en(v.out, v.back)
    if not found:
        return None
    d, name = found[0]
    kind = "Puente" if any(x.weekday() in (0, 4) for x, _ in found) else "Festivo"
    return f"🎉 {kind}: {fmt_date_short(d.isoformat(), today)}, {name}"


def _history_line(v: Verdict) -> str | None:
    if v.stage != 2:
        return None
    if v.new_low and v.tracked_days:
        return f"📉 El más barato en {v.tracked_days:.0f} días de seguimiento"
    if v.percentile is not None and v.percentile < 5:
        return "📉 Casi nunca ha estado así de barato"
    return None


def _connection_lines(config: Config, v: Verdict) -> list[str]:
    """Internacional: de dónde sale y el total sumando la conexión desde casa."""
    if v.zone.kind != "international" or v.origin == config.home:
        return []
    home, hub = config.city(v.feeder_origin or config.home), config.city(v.origin)
    if v.feeder_price is None:
        return [f"✈️ Sale de {hub} · falta sumar el vuelo desde {home}"]
    approx = " (aprox.)" if v.feeder_estimated else ""
    return [
        f"✈️ Sale de {hub} · {home} ⇄ {hub}: {fmt_price(v.feeder_price, v.currency)}{approx}",
        f"🧾 *Total desde {home}: {(fmt_approx(v.total, v.currency) if v.feeder_estimated else fmt_price(v.total, v.currency))}*",
    ]


# -- aviso inmediato 🔥 ---------------------------------------------------------

def format_super_alert(config: Config, v: Verdict, today: date) -> str:
    kind = "solo ida" if v.one_way else "ida y vuelta"
    lines = [
        "🔥 *SÚPER BARATO · SOLO IDA*" if v.one_way else "🔥 *SÚPER BARATO*",
        f"{_icon(v)} *{_title(config, v)} · {fmt_price(v.price, v.currency)}* {kind}",
    ]
    normally = _normally(v)
    if normally:
        lines.append(normally)
    lines.append("")
    when = fmt_date_short(v.out, today) if v.one_way else f"{fmt_trip_short(v.out, v.back, today)} · {fmt_nights(v.nights)}"
    lines.append(f"📅 {when}")
    for extra in (_holiday_short(v, today), _bags_line(v)):
        if extra:
            lines.append(extra)
    if v.split_price is not None:
        lines.append(f"✂️ En dos tramos solo ida: {fmt_price(v.split_price, v.currency)}")
    lines.extend(_connection_lines(config, v))
    history = _history_line(v)
    if history:
        lines.append(history)
    lines.append(link("👉 Ver vuelo", _link(config, v)))
    return "\n".join(lines)


def _item(config: Config, v: Verdict, today: date, icon: str | None = None) -> str:
    """Una línea por destino (y una segunda solo si hace falta), para listas y el resumen."""
    savings = f" · −{fmt_percent(v.savings_percent)}" if v.savings_percent >= 10 else ""
    party = " 🎉" if festivos_en(v.out, v.back) else ""
    line = (
        f"• {icon or _icon(v)} *{link(_title(config, v), _link(config, v))}* "
        f"{fmt_price(v.price, v.currency)} · {fmt_range(v.out, v.back, today)}{party}{savings}"
    )
    extra = []
    if v.split_price is not None:
        extra.append(f"en dos tramos solo ida: {fmt_price(v.split_price, v.currency)}")
    if v.zone.kind == "international" and v.origin != config.home:
        via = f"sale de {config.city(v.origin)}"
        if v.feeder_price is not None:
            via += f" · total desde {config.city(v.feeder_origin or config.home)} {fmt_approx(v.total, v.currency)}"
        extra.append(via)
    return "\n".join([line] + [f"   {e}" for e in extra])


def format_alerts_packed(config: Config, verdicts: list[Verdict], today: date) -> list[tuple[str, list[Verdict]]]:
    """Avisos 🔥 empaquetados en mensajes, con los veredictos que lleva cada uno."""
    ordered = sorted(verdicts, key=lambda v: (-v.savings_percent, v.total))
    if len(ordered) < COMPACT_FROM:
        return pack([Piece(format_super_alert(config, v, today) + "\n", verdicts=(v,)) for v in ordered])
    title = f"🔥 *{len(ordered)} vuelos súper baratos*"
    pieces = [Piece(title), Piece(_prices_note(config) + "\n")]
    for kind in KINDS:
        items = [v for v in ordered if v.zone.kind == kind]
        if not items:
            continue
        header = f"{KIND_HEADER[kind]} · {_origin_text(config, kind)}"
        pieces.append(Piece(header, context=title + " (sigue)"))
        for v in items:
            pieces.append(Piece(_item(config, v, today), context=f"{header} (sigue)", verdicts=(v,)))
        pieces.append(Piece(""))
    while pieces and pieces[-1].text == "":
        pieces.pop()
    return pack(pieces)


def format_alerts(config: Config, verdicts: list[Verdict], today: date) -> list[str]:
    return texts(format_alerts_packed(config, verdicts, today))


# -- resumen diario ☀️ -----------------------------------------------------------

def _origin_text(config: Config, kind: str) -> str:
    if kind == "domestic":
        return f"desde {config.city(config.home)}"
    origins = dict.fromkeys(o for z in config.zones_of_kind(kind) for o in z.origins)
    return "desde " + " o ".join(config.city(o) for o in origins)


def _prices_note(config: Config) -> str:
    """'Ida y vuelta, por persona. Colombia sin maleta; internacional con maleta.'"""
    parts = []
    for kind, label in (("domestic", "Colombia"), ("international", "internacional")):
        bags = {z.bags for z in config.zones_of_kind(kind)}
        if len(bags) == 1:
            parts.append(f"{label} {BAGS_TEXT[bags.pop()].split(' facturada')[0]}")
    return "Ida y vuelta, por persona" + (". " + "; ".join(parts).capitalize() + "." if parts else ".")


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
    pieces = [Piece(f"☀️ *Vuelos baratos hoy* · {fmt_date_long(today.isoformat())}"), Piece(_prices_note(config) + "\n")]
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
                pieces.append(Piece(f"   …y {len(items) - limit} más"))
        one_way = sorted((v for v in verdicts if v.one_way and v.level), key=lambda v: (LEVEL_RANK[v.level], -v.savings_percent, v.price))
        if one_way:
            anything = True
            pieces.append(Piece(ONE_WAY_TITLE, context=f"{header} (sigue)"))
            for v in one_way[:limit]:
                icon = "🔥" if v.level == SUPER else "👍"
                pieces.append(Piece(_item(config, v, today, icon=icon), context=f"{header} (sigue)\n{ONE_WAY_TITLE}"))
            if len(one_way) > limit:
                pieces.append(Piece(f"   …y {len(one_way) - limit} más"))
        if verdicts and not any(v.level for v in verdicts):
            pieces.append(Piece("Nada barato hoy. Te aviso apenas aparezca algo."))
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
    pieces = [Piece("📅 *Plan de viajes* · lo más barato de cada zona"), Piece(_prices_note(config) + "\n")]
    for kind in KINDS:
        rows = rows_by_kind.get(kind)
        if rows is None:
            continue
        header = f"{KIND_HEADER[kind]} · {_origin_text(config, kind)}"
        pieces.append(Piece(header))
        if not rows:
            pieces.append(Piece("Aún no hay datos."))
        for v, month in rows:
            mark = {SUPER: " 🔥", CHEAP: " 👍"}.get(v.level, "")
            city = config.city(v.destination)
            place = link(city, _link(config, v))
            label = f"{v.zone.emoji} *{place}*" if city == v.zone.name else f"{v.zone.emoji} {v.zone.name}: *{place}*"
            lines = [f"{label} {fmt_price(v.price, v.currency)} · {fmt_range(v.out, v.back, today)}{mark}"]
            if v.zone.kind == "international" and v.feeder_price is not None:
                lines.append(f"   sale de {config.city(v.origin)} · total desde {config.city(v.feeder_origin or config.home)} {fmt_approx(v.total, v.currency)}")
            if month and month[1] >= 3:  # con 1 o 2 fechas no dice nada útil
                lines.append(f"   mejor mes para ir: {month[0]}")
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
        "🔥 *Súper barato* → te escribo apenas aparece una ganga de verdad (casi la mitad de lo normal).\n"
        "☀️ *Resumen* → todos los días a las 7:30 a. m., con lo 🔥 y lo 👍 barato.\n"
        "📅 *Plan de viajes* → los lunes.\n"
        "Busco ida y vuelta, con y sin maleta, y en Colombia también solo ida."
    )
    pieces = [Piece(intro + "\n")]
    if sample:
        pieces.append(Piece("Así se ve un aviso (ejemplo con precios reales guardados):\n"))
        pieces.append(Piece(format_super_alert(config, sample, today)))
    return texts(pack(pieces))
