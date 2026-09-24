"""Envío de mensajes por varios canales, configurados con variables de entorno:

  Telegram (recomendado: gratis e ilimitado)
      TELEGRAM_BOT_TOKEN  token de @BotFather
      TELEGRAM_CHAT_ID    tu Id (te lo da @userinfobot)
  WhatsApp vía Whapi.Cloud (sandbox gratis: 150 mensajes/día)
      WHAPI_TOKEN, WHAPI_PHONE (con indicativo, sin +, ej. 573001234567)
  WhatsApp vía CallMeBot (gratis, pero suele estar lleno)
      CALLMEBOT_PHONE, CALLMEBOT_APIKEY
  ntfy.sh (notificación push, sin registro)
      NTFY_TOPIC (y opcional NTFY_SERVER)

Si hay varios, se envía por todos. Si no hay ninguno, se imprime en consola.
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Callable, Protocol

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 30.0
LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
BOLD_RE = re.compile(r"\*([^*\n]+)\*")


# -- conversión del marcado a cada canal ---------------------------------------

def to_telegram_html(text: str) -> str:
    """*negrita* → <b>, [texto](url) → <a href>. Escapa todo lo demás."""
    escaped = html.escape(text, quote=False)
    escaped = LINK_RE.sub(lambda m: f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1)}</a>', escaped)
    return BOLD_RE.sub(r"<b>\1</b>", escaped)


def to_plain(text: str, keep_bold: bool = True, inline_urls: bool = False) -> str:
    """Texto plano. keep_bold: deja *negrita* (WhatsApp). inline_urls: pone la URL de los
    enlaces que van dentro de una línea en la línea siguiente (para poder abrirlos en WhatsApp)."""
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        whole = LINK_RE.fullmatch(stripped)
        if whole:
            out.append(line[: len(line) - len(line.lstrip())] + f"{whole.group(1)}: {whole.group(2)}")
            continue
        urls = [m.group(2) for m in LINK_RE.finditer(line)]
        out.append(LINK_RE.sub(r"\1", line))
        if inline_urls:
            out.extend(f"   👉 {u}" for u in urls)
    result = "\n".join(out)
    if not keep_bold:
        result = BOLD_RE.sub(r"\1", result)
    return result


# -- canales ----------------------------------------------------------------------

class Notifier(Protocol):
    name: str

    def send(self, text: str) -> bool: ...


class ConsoleNotifier:
    """Imprime en pantalla. Se usa en --dry-run o cuando no hay canales."""

    name = "consola (sin canal configurado)"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        print("\n----- MENSAJE -----\n" + to_plain(text, inline_urls=True) + "\n-------------------")
        return True


class TelegramNotifier:
    name = "Telegram"

    def __init__(
        self,
        token: str,
        chat_id: str,
        session: requests.Session | None = None,
        silent: Callable[[], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self.session = session or requests.Session()
        self.silent = silent or (lambda: False)
        self.sleep = sleep
        self.clock = time.monotonic
        self._last_sent: float | None = None

    def _redact(self, text: str) -> str:
        return text.replace(self.token, "***") if self.token else text

    def _post(self, payload: dict) -> requests.Response | None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        resp = None
        for attempt in range(3):
            # Telegram pide no más de 1 mensaje por segundo al mismo chat.
            if self._last_sent is not None:
                gap = self.clock() - self._last_sent
                if gap < 1.1:
                    self.sleep(1.1 - gap)
            try:
                resp = self.session.post(url, json=payload, timeout=TIMEOUT)
            except requests.RequestException as exc:
                logger.error("Telegram no respondió: %s", self._redact(str(exc)))
                resp = None
                if attempt < 2:
                    self.sleep(3.0)
                    continue
                return None
            finally:
                self._last_sent = self.clock()
            if resp.status_code == 429 and attempt < 2:
                try:
                    wait = float(resp.json().get("parameters", {}).get("retry_after", 5))
                except (ValueError, AttributeError):
                    wait = 5.0
                if wait > 60:
                    logger.error("Telegram pide esperar %.0f s: se abandona este mensaje", wait)
                    return resp
                self.sleep(wait + 1)
                continue
            return resp
        return resp

    def send(self, text: str) -> bool:
        payload = {
            "chat_id": self.chat_id,
            "text": to_telegram_html(text),
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "disable_notification": bool(self.silent()),
        }
        resp = self._post(payload)
        if resp is not None and resp.status_code == 400 and "parse" in resp.text.lower():
            # Si algún día el formato falla, mejor llegar sin negritas que no llegar.
            logger.warning("Telegram rechazó el formato; se reenvía como texto simple")
            payload.pop("parse_mode")
            payload["text"] = to_plain(text, keep_bold=False)
            resp = self._post(payload)
        ok = resp is not None and resp.status_code == 200
        if not ok and resp is not None:
            logger.error("Telegram devolvió %s: %s", resp.status_code, self._redact(resp.text[:300]))
        return ok


class WhapiNotifier:
    """WhatsApp a través de https://whapi.cloud (API no oficial; sandbox gratis)."""

    name = "WhatsApp (Whapi)"

    def __init__(self, token: str, phone: str, session: requests.Session | None = None):
        self.token = token.strip()
        self.phone = re.sub(r"\D", "", phone)
        self.session = session or requests.Session()

    def send(self, text: str) -> bool:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            resp = self.session.post(
                "https://gate.whapi.cloud/messages/text",
                headers=headers,
                json={"to": self.phone, "body": to_plain(text, inline_urls=True)},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.error("Whapi no respondió: %s", exc.__class__.__name__)
            return False
        ok = 200 <= resp.status_code < 300
        if not ok:
            logger.error("Whapi devolvió %s: %s", resp.status_code, resp.text[:200])
        return ok


class CallMeBotNotifier:
    name = "WhatsApp (CallMeBot)"

    def __init__(self, phone: str, apikey: str, session: requests.Session | None = None):
        self.phone = re.sub(r"\D", "", phone)
        self.apikey = apikey.strip()
        self.session = session or requests.Session()

    def send(self, text: str) -> bool:
        params = {"phone": self.phone, "text": to_plain(text, inline_urls=True), "apikey": self.apikey}
        url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        try:
            resp = self.session.get(url, timeout=TIMEOUT)
        except requests.RequestException as exc:
            logger.error("CallMeBot no respondió: %s", exc.__class__.__name__)
            return False
        ok = resp.status_code in (200, 203) and "error" not in resp.text.lower()[:200]
        if not ok:
            logger.error("CallMeBot devolvió %s: %s", resp.status_code, resp.text[:200])
        return ok


class NtfyNotifier:
    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh", session: requests.Session | None = None):
        self.topic = topic.strip().strip("/")
        self.server = server.rstrip("/")
        self.session = session or requests.Session()

    def send(self, text: str) -> bool:
        plain = to_plain(text, keep_bold=False)
        title, _, body = plain.partition("\n")
        payload = {"topic": self.topic, "title": title, "message": body.strip() or title, "tags": ["airplane"]}
        try:
            resp = self.session.post(self.server + "/", json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            logger.error("ntfy no respondió: %s", exc.__class__.__name__)
            return False
        return resp.status_code == 200


class MultiNotifier:
    """Envía por todos los canales; True si al menos uno funcionó."""

    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers
        self.name = " + ".join(n.name for n in notifiers)

    def send(self, text: str) -> bool:
        results = [n.send(text) for n in self.notifiers]
        for n, ok in zip(self.notifiers, results):
            if not ok:
                logger.warning("Falló el envío por %s", n.name)
        return any(results)


def in_quiet_hours(quiet: tuple[int, int] | None, now: datetime | None = None) -> bool:
    """¿Es de noche en Colombia (UTC−5) según [inicio, fin]?"""
    if not quiet:
        return False
    from .config import COLOMBIA_TZ

    hour = (now or datetime.now(timezone.utc)).astimezone(COLOMBIA_TZ).hour
    start, end = quiet
    if start == end:
        return False
    return start <= hour or hour < end if start > end else start <= hour < end


def notifiers_from_env(env: dict[str, str] | None = None, quiet_hours: tuple[int, int] | None = None) -> list[Notifier]:
    env = os.environ if env is None else env
    found: list[Notifier] = []
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        found.append(
            TelegramNotifier(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"], silent=lambda: in_quiet_hours(quiet_hours))
        )
    if env.get("WHAPI_TOKEN") and env.get("WHAPI_PHONE"):
        found.append(WhapiNotifier(env["WHAPI_TOKEN"], env["WHAPI_PHONE"]))
    if env.get("CALLMEBOT_PHONE") and env.get("CALLMEBOT_APIKEY"):
        found.append(CallMeBotNotifier(env["CALLMEBOT_PHONE"], env["CALLMEBOT_APIKEY"]))
    if env.get("NTFY_TOPIC"):
        found.append(NtfyNotifier(env["NTFY_TOPIC"], env.get("NTFY_SERVER", "https://ntfy.sh")))
    return found


def build_notifier(dry_run: bool = False, quiet_hours: tuple[int, int] | None = None) -> Notifier:
    if dry_run:
        return ConsoleNotifier()
    found = notifiers_from_env(quiet_hours=quiet_hours)
    if not found:
        return ConsoleNotifier()
    return found[0] if len(found) == 1 else MultiNotifier(found)


def is_real(notifier: Notifier) -> bool:
    return not isinstance(notifier, ConsoleNotifier)
