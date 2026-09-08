"""Envío de avisos por varios canales. Se activan con variables de entorno:

  Telegram (recomendado, gratis e ilimitado)
      TELEGRAM_BOT_TOKEN  token de @BotFather
      TELEGRAM_CHAT_ID    tu chat id (lo da @userinfobot)
  WhatsApp vía Whapi.Cloud (sandbox gratis: 150 mensajes/día)
      WHAPI_TOKEN         token del canal
      WHAPI_PHONE         tu número con indicativo, sin +  (ej. 573001234567)
  WhatsApp vía CallMeBot (gratis, pero suele estar lleno)
      CALLMEBOT_PHONE, CALLMEBOT_APIKEY
  ntfy.sh (push a la app ntfy, sin registro)
      NTFY_TOPIC          nombre de tema difícil de adivinar

Si hay varias configuradas, se envía por todas. Si no hay ninguna, imprime en consola.
"""

from __future__ import annotations

import html
import logging
import os
import re
import urllib.parse
from datetime import datetime
from typing import Protocol

import requests

from .alerts import Alert

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 1500  # los mensajes cortos se leen mejor en el celular
TIMEOUT = 30.0


class Notifier(Protocol):
    name: str

    def send(self, text: str) -> bool: ...


def _safe_get(session: requests.Session, name: str, url: str, **kwargs) -> requests.Response | None:
    try:
        return session.get(url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        logger.error("%s no respondió: %s", name, exc)
        return None


def _safe_post(session: requests.Session, name: str, url: str, **kwargs) -> requests.Response | None:
    try:
        return session.post(url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        logger.error("%s no respondió: %s", name, exc)
        return None


class ConsoleNotifier:
    """Imprime en pantalla. Se usa en --dry-run o cuando no hay credenciales."""

    name = "consola"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        print("\n----- MENSAJE -----\n" + text + "\n-------------------")
        return True


class TelegramNotifier:
    name = "Telegram"

    def __init__(self, token: str, chat_id: str, session: requests.Session | None = None):
        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self.session = session or requests.Session()

    @staticmethod
    def to_html(text: str) -> str:
        """Convierte *negrita* estilo WhatsApp a <b>negrita</b> y escapa el resto."""
        escaped = html.escape(text, quote=False)
        return re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", escaped)

    def send(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": self.to_html(text),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        resp = _safe_post(self.session, self.name, url, json=payload)
        ok = resp is not None and resp.status_code == 200
        if not ok and resp is not None:
            logger.error("Telegram devolvió %s: %s", resp.status_code, resp.text[:200])
        return ok


class WhapiNotifier:
    """WhatsApp a través de https://whapi.cloud (API no oficial; sandbox gratis)."""

    name = "WhatsApp (Whapi)"

    def __init__(self, token: str, phone: str, session: requests.Session | None = None):
        self.token = token.strip()
        self.phone = re.sub(r"\D", "", phone)
        self.session = session or requests.Session()

    def send(self, text: str) -> bool:
        url = "https://gate.whapi.cloud/messages/text"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        resp = _safe_post(self.session, self.name, url, headers=headers, json={"to": self.phone, "body": text})
        ok = resp is not None and 200 <= resp.status_code < 300
        if not ok and resp is not None:
            logger.error("Whapi devolvió %s: %s", resp.status_code, resp.text[:200])
        return ok


class CallMeBotNotifier:
    name = "WhatsApp (CallMeBot)"

    def __init__(self, phone: str, apikey: str, session: requests.Session | None = None):
        self.phone = re.sub(r"\D", "", phone)
        self.apikey = apikey.strip()
        self.session = session or requests.Session()

    def send(self, text: str) -> bool:
        params = {"phone": self.phone, "text": text, "apikey": self.apikey}
        url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        resp = _safe_get(self.session, self.name, url)
        ok = resp is not None and resp.status_code in (200, 203) and "error" not in resp.text.lower()[:200]
        if not ok and resp is not None:
            logger.error("CallMeBot devolvió %s: %s", resp.status_code, resp.text[:200])
        return ok


class NtfyNotifier:
    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh", session: requests.Session | None = None):
        self.topic = topic.strip().strip("/")
        self.server = server.rstrip("/")
        self.session = session or requests.Session()

    def send(self, text: str) -> bool:
        title, _, body = text.partition("\n")
        headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Tags": "airplane"}
        resp = _safe_post(self.session, self.name, f"{self.server}/{self.topic}", data=(body or title).encode("utf-8"), headers=headers)
        return resp is not None and resp.status_code == 200


class MultiNotifier:
    """Envía por todos los canales; devuelve True si al menos uno funcionó."""

    name = "multi"

    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def send(self, text: str) -> bool:
        results = [n.send(text) for n in self.notifiers]
        for n, ok in zip(self.notifiers, results):
            if not ok:
                logger.warning("Falló el envío por %s", n.name)
        return any(results)


def notifiers_from_env(env: dict[str, str] | None = None) -> list[Notifier]:
    env = os.environ if env is None else env
    found: list[Notifier] = []
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        found.append(TelegramNotifier(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"]))
    if env.get("WHAPI_TOKEN") and env.get("WHAPI_PHONE"):
        found.append(WhapiNotifier(env["WHAPI_TOKEN"], env["WHAPI_PHONE"]))
    if env.get("CALLMEBOT_PHONE") and env.get("CALLMEBOT_APIKEY"):
        found.append(CallMeBotNotifier(env["CALLMEBOT_PHONE"], env["CALLMEBOT_APIKEY"]))
    if env.get("NTFY_TOPIC"):
        found.append(NtfyNotifier(env["NTFY_TOPIC"], env.get("NTFY_SERVER", "https://ntfy.sh")))
    return found


def build_notifier(dry_run: bool = False) -> Notifier:
    if dry_run:
        return ConsoleNotifier()
    found = notifiers_from_env()
    if not found:
        logger.warning("Sin canales configurados (TELEGRAM_*, WHAPI_*, CALLMEBOT_*, NTFY_TOPIC): se imprime en consola")
        return ConsoleNotifier()
    logger.info("Canales activos: %s", ", ".join(n.name for n in found))
    return found[0] if len(found) == 1 else MultiNotifier(found)


# -- formato de mensajes ------------------------------------------------------

def fmt_price(price: float, currency: str) -> str:
    if currency == "COP":
        return f"${price:,.0f} COP".replace(",", ".")
    return f"{price:,.0f} {currency}"


def fmt_date(day: str) -> str:
    """'2026-10-12' -> 'lun 12 oct 2026'."""
    d = datetime.strptime(day, "%Y-%m-%d")
    dias = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{dias[d.weekday()]} {d.day} {meses[d.month - 1]} {d.year}"


def google_flights_link(origin: str, destination: str, day: str, currency: str, language: str, country: str) -> str:
    q = f"Flights from {origin} to {destination} on {day} one way"
    return "https://www.google.com/travel/flights?" + urllib.parse.urlencode(
        {"q": q, "curr": currency, "hl": language, "gl": country}
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
