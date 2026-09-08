from cheapflights.notify import (
    CallMeBotNotifier,
    MultiNotifier,
    NtfyNotifier,
    TelegramNotifier,
    WhapiNotifier,
    notifiers_from_env,
)


class FakeResp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.resp

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.resp


def test_telegram_converts_bold_to_html_and_escapes():
    assert TelegramNotifier.to_html("*BGA → BOG*: 1 < 2 & *x*") == "<b>BGA → BOG</b>: 1 &lt; 2 &amp; <b>x</b>"


def test_telegram_sends_html_payload():
    s = FakeSession(FakeResp(200))
    n = TelegramNotifier("123:abc", "42", session=s)
    assert n.send("*hola*") is True
    method, url, kw = s.calls[0]
    assert method == "POST" and url.endswith("/bot123:abc/sendMessage")
    assert kw["json"]["text"] == "<b>hola</b>" and kw["json"]["parse_mode"] == "HTML"


def test_telegram_failure():
    assert TelegramNotifier("t", "c", session=FakeSession(FakeResp(401, "Unauthorized"))).send("x") is False


def test_whapi_payload():
    s = FakeSession(FakeResp(201))
    assert WhapiNotifier("tok", "+57 300 123 4567", session=s).send("hola") is True
    _, url, kw = s.calls[0]
    assert url == "https://gate.whapi.cloud/messages/text"
    assert kw["json"] == {"to": "573001234567", "body": "hola"}
    assert kw["headers"]["Authorization"] == "Bearer tok"


def test_callmebot_builds_url():
    s = FakeSession(FakeResp(200, "Message queued"))
    assert CallMeBotNotifier("+573001234567", "abc", session=s).send("hola mundo") is True
    assert "phone=573001234567" in s.calls[0][1] and "text=hola%20mundo" in s.calls[0][1]


def test_ntfy_uses_first_line_as_title():
    s = FakeSession(FakeResp(200))
    assert NtfyNotifier("mi-tema", session=s).send("Titulo\ncuerpo") is True
    _, url, kw = s.calls[0]
    assert url == "https://ntfy.sh/mi-tema" and kw["data"] == b"cuerpo"


def test_multi_returns_true_if_any_ok():
    ok = TelegramNotifier("t", "c", session=FakeSession(FakeResp(200)))
    bad = TelegramNotifier("t", "c", session=FakeSession(FakeResp(500)))
    assert MultiNotifier([bad, ok]).send("x") is True
    assert MultiNotifier([bad]).send("x") is False


def test_notifiers_from_env_picks_configured():
    found = notifiers_from_env({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c", "NTFY_TOPIC": "z", "WHAPI_TOKEN": "solo-token"})
    assert [n.name for n in found] == ["Telegram", "ntfy"]
    assert notifiers_from_env({}) == []
