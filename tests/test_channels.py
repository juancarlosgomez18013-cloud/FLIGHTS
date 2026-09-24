from datetime import datetime, timezone

from cheapflights.notify import (
    CallMeBotNotifier,
    MultiNotifier,
    NtfyNotifier,
    TelegramNotifier,
    WhapiNotifier,
    in_quiet_hours,
    notifiers_from_env,
    to_telegram_html,
)


class FakeResp:
    def __init__(self, status, text="", data=None):
        self.status_code, self.text, self._data = status, text, data or {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, *resps):
        self.resps, self.calls = list(resps), []

    def _next(self):
        return self.resps.pop(0) if len(self.resps) > 1 else self.resps[0]

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self._next()

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self._next()


def test_telegram_html_escapes_and_converts():
    assert to_telegram_html("*BGA → BOG*: 1 < 2 & *x*") == "<b>BGA → BOG</b>: 1 &lt; 2 &amp; <b>x</b>"
    assert to_telegram_html("[Ver](https://a.com/?x=1&y=2)") == '<a href="https://a.com/?x=1&amp;y=2">Ver</a>'


def test_telegram_payload():
    s = FakeSession(FakeResp(200))
    n = TelegramNotifier("123:abc", "42", session=s, silent=lambda: True)
    assert n.send("*hola*") is True
    method, url, kw = s.calls[0]
    assert method == "POST" and url.endswith("/bot123:abc/sendMessage")
    p = kw["json"]
    assert p["text"] == "<b>hola</b>" and p["parse_mode"] == "HTML"
    assert p["disable_notification"] is True and p["link_preview_options"] == {"is_disabled": True}


def test_telegram_falls_back_to_plain_text_on_parse_error():
    s = FakeSession(FakeResp(400, '{"description":"Bad Request: can\'t parse entities"}'), FakeResp(200))
    assert TelegramNotifier("t", "c", session=s).send("*hola* [x](https://a.com)") is True
    retry = s.calls[1][2]["json"]
    assert "parse_mode" not in retry and retry["text"] == "hola x"


def _tg(session, waits):
    n = TelegramNotifier("t", "c", session=session, sleep=waits.append)
    n.clock = lambda: 1000.0 + len(waits) * 100  # el tiempo avanza solo cuando se duerme
    return n


def test_telegram_waits_what_telegram_asks_on_429():
    waits = []
    s = FakeSession(FakeResp(429, "", {"parameters": {"retry_after": 35}}), FakeResp(200))
    assert _tg(s, waits).send("x") is True
    assert waits == [36.0] and len(s.calls) == 2


def test_telegram_gives_up_if_wait_is_too_long():
    waits = []
    s = FakeSession(FakeResp(429, "", {"parameters": {"retry_after": 600}}))
    assert _tg(s, waits).send("x") is False and waits == []


def test_telegram_spaces_consecutive_messages():
    waits = []
    n = TelegramNotifier("t", "c", session=FakeSession(FakeResp(200)), sleep=waits.append)
    n.clock = lambda: 5.0  # sin tiempo transcurrido entre envíos
    n.send("a")
    n.send("b")
    assert waits and waits[-1] >= 1.0


def test_telegram_retries_network_errors():
    import requests

    class Flaky(FakeSession):
        def post(self, url, **kw):
            self.calls.append(("POST", url, kw))
            if len(self.calls) == 1:
                raise requests.ConnectionError("boom SECRETTOKEN")
            return FakeResp(200)

    waits = []
    n = TelegramNotifier("SECRETTOKEN", "c", session=Flaky(FakeResp(200)), sleep=waits.append)
    n.clock = lambda: 1000.0 + len(waits) * 100
    assert n.send("x") is True


def test_telegram_error_does_not_leak_token(caplog):
    s = FakeSession(FakeResp(401, "Unauthorized for bot SECRET123"))
    assert TelegramNotifier("SECRET123", "c", session=s).send("x") is False
    assert "SECRET123" not in caplog.text


def test_whapi_payload_is_plain_text():
    s = FakeSession(FakeResp(201))
    assert WhapiNotifier("tok", "+57 300 123 4567", session=s).send("*hola* [ver](https://a.com)") is True
    _, url, kw = s.calls[0]
    assert url == "https://gate.whapi.cloud/messages/text"
    assert kw["json"] == {"to": "573001234567", "body": "*hola* ver\n   👉 https://a.com"}


def test_callmebot_builds_url():
    s = FakeSession(FakeResp(200, "Message queued"))
    assert CallMeBotNotifier("+573001234567", "abc", session=s).send("hola mundo") is True
    assert "phone=573001234567" in s.calls[0][1] and "text=hola%20mundo" in s.calls[0][1]


def test_ntfy_json_publish_keeps_utf8_title():
    s = FakeSession(FakeResp(200))
    assert NtfyNotifier("mi-tema", session=s).send("🔥 *Título*\ncuerpo") is True
    _, url, kw = s.calls[0]
    assert url == "https://ntfy.sh/"
    assert kw["json"]["topic"] == "mi-tema" and kw["json"]["title"] == "🔥 Título" and kw["json"]["message"] == "cuerpo"


def test_multi_returns_true_if_any_ok():
    ok = TelegramNotifier("t", "c", session=FakeSession(FakeResp(200)))
    bad = TelegramNotifier("t", "c", session=FakeSession(FakeResp(500)))
    assert MultiNotifier([bad, ok]).send("x") is True
    assert MultiNotifier([bad]).send("x") is False


def test_notifiers_from_env_picks_configured():
    found = notifiers_from_env({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c", "NTFY_TOPIC": "z", "WHAPI_TOKEN": "solo"})
    assert [n.name for n in found] == ["Telegram", "ntfy"]
    assert notifiers_from_env({}) == []


def test_quiet_hours_colombia_time():
    at = lambda h: datetime(2026, 9, 23, (h + 5) % 24, 0, tzinfo=timezone.utc)  # h = hora Colombia
    assert in_quiet_hours((22, 6), at(23)) and in_quiet_hours((22, 6), at(3))
    assert not in_quiet_hours((22, 6), at(7)) and not in_quiet_hours((22, 6), at(21))
    assert in_quiet_hours((1, 4), at(2)) and not in_quiet_hours((1, 4), at(5))
    assert not in_quiet_hours(None, at(3))
