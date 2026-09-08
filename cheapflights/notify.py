"""Envío de mensajes: WhatsApp vía CallMeBot, o consola si no hay credenciales.

CallMeBot es gratis para uso personal y solo puede escribir a TU propio número.
Registro: https://www.callmebot.com/blog/free-api-whatsapp-messages/
Variables de entorno: CALLMEBOT_PHONE (con indicativo, ej. 573001234567) y CALLMEBOT_APIKEY.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from datetime import datetime
from typing import Protocol

import requests

from .alerts import Alert

logger = logging.getLogger(__name__)

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
MAX_MESSAGE_CHARS = 1500  # WhatsApp permite más, pero mensajes cortos se leen mejor


class Notifier(Protocol):
    def send(self, text: str) -> bool: ...


class ConsoleNotifier:
    """Imprime en pantalla. Se usa en --dry-run o cuando no hay credenciales."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        print("\n----- MENSAJE -----\n" + text + "\n-------------------")
        return True


class CallMeBotNotifier:
    def __init__(self, phone: str, apikey: str, session: requests.Session | None = None, timeout: float = 30.0):
        self.phone = phone.strip().lstrip("+")
        self.apikey = apikey.strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "CallMeBotNotifier | None":
        phone = os.environ.get("CALLMEBOT_PHONE")
        apikey = os.environ.get("CALLMEBOT_APIKEY")
        if phone and apikey:
            return cls(phone, apikey)
        return None

    def send(self, text: str) -> bool:
        params = {"phone": self.phone, "text": text, "apikey": self.apikey}
        url = CALLMEBOT_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.error("CallMeBot no respondió: %s", exc)
            return False
        ok = resp.status_code in (200, 203) and "error" not in resp.text.lower()[:200]
        if not ok:
            logger.error("CallMeBot devolvió %s: %s", resp.status_code, resp.text[:200])
        return ok


def build_notifier(dry_run: bool = False) -> Notifier:
    if dry_run:
        return ConsoleNotifier()
    real = CallMeBotNotifier.from_env()
    if real is None:
        logger.warning("Sin CALLMEBOT_PHONE/CALLMEBOT_APIKEY: los avisos se imprimen en consola")
        return ConsoleNotifier()
    return real


# -- formato de mensajes ------------------------------------------------------

def fmt_price(price: float, currency: str) -> str:
    if currency == "COP":
        return f"${price:,.0f} COP".replace(",", ".")
    return f"{price:,.0f} {currency}"


def fmt_date(day: str) -> str:
    """'2026-10-12' -> 'dom 12 oct 2026'."""
    d = datetime.strptime(day, "%Y-%m-%d")
    dias = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{dias[d.weekday()]} {d.day} {meses[d.month - 1]} {d.year}"


def google_flights_link(origin: str, destination: str, day: str, currency: str, language: str, country: str) -> str:
    q = f"Flights from {origin} to {destination} on {day} one way"
    return (
        "https://www.google.com/travel/flights?"
        + urllib.parse.urlencode({"q": q, "curr": currency, "hl": language, "gl": country})
    )


KIND_LABEL = {
    "target": "🎯 Bajo tu precio objetivo",
    "new_low": "📉 Mínimo histórico",
    "drop": "🔻 Bajó fuerte",
}


def format_alert(alert: Alert, language: str, country: str) -> str:
    lines = [
        f"{KIND_LABEL[alert.kind]} · {alert.group}",
        f"*{alert.origin} → {alert.destination}*: *{fmt_price(alert.price, alert.currency)}* el {fmt_date(alert.date)}",
    ]
    if alert.kind == "target":
        lines.append(f"Objetivo: {fmt_price(alert.previous, alert.currency)}")
    elif alert.kind == "new_low":
        lines.append(f"Mínimo anterior: {fmt_price(alert.previous, alert.currency)}")
    elif alert.kind == "drop":
        pct = 100 * (alert.previous - alert.price) / alert.previous
        lines.append(f"Antes: {fmt_price(alert.previous, alert.currency)} (−{pct:.0f}%)")
    if alert.percentile is not None:
        lines.append(f"Solo el {alert.percentile:.0f}% de las veces ha estado más barato")
    lines.append(google_flights_link(alert.origin, alert.destination, alert.date, alert.currency, language, country))
    return "\n".join(lines)


def format_alerts_batch(alerts: list[Alert], language: str, country: str) -> list[str]:
    """Agrupa varias alertas en pocos mensajes (máx ~1500 caracteres cada uno)."""
    messages: list[str] = []
    current: list[str] = []
    size = 0
    for alert in alerts:
        block = format_alert(alert, language, country)
        if current and size + len(block) + 2 > MAX_MESSAGE_CHARS:
            messages.append("\n\n".join(current))
            current, size = [], 0
        current.append(block)
        size += len(block) + 2
    if current:
        messages.append("\n\n".join(current))
    return messages
