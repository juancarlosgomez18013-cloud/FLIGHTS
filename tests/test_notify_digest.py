from datetime import date, timedelta

from cheapflights.alerts import Alert
from cheapflights.digest import build_digest, group_deals
from cheapflights.notify import CallMeBotNotifier, fmt_date, fmt_price, format_alert, format_alerts_batch
from cheapflights.search import RouteResult


def test_fmt_price_cop():
    assert fmt_price(1234567, "COP") == "$1.234.567 COP"
    assert fmt_price(99.9, "USD") == "100 USD"


def test_fmt_date_spanish():
    assert fmt_date("2026-10-12") == "lun 12 oct 2026"


def test_format_alert_contains_link_and_price():
    a = Alert(kind="new_low", group="Colombia", origin="BGA", destination="BOG", price=120000, date="2026-10-12", currency="COP", previous=150000)
    text = format_alert(a, "es", "CO")
    assert "Mínimo histórico" in text
    assert "$120.000 COP" in text
    assert "google.com/travel/flights" in text and "BGA" in text and "2026-10-12" in text


def test_batch_splits_long_messages():
    alerts = [
        Alert(kind="target", group="Colombia", origin="BGA", destination=f"X{i:02d}"[:3], price=1000, date="2026-10-12", currency="COP", previous=2000)
        for i in range(40)
    ]
    msgs = format_alerts_batch(alerts, "es", "CO")
    assert len(msgs) > 1
    assert all(len(m) <= 1600 for m in msgs)


class FakeResp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, timeout):
        self.calls.append(url)
        return self.resp


def test_callmebot_builds_url_and_detects_ok():
    s = FakeSession(FakeResp(200, "Message queued"))
    n = CallMeBotNotifier("+573001234567", "abc", session=s)
    assert n.send("hola mundo") is True
    assert "phone=573001234567" in s.calls[0] and "text=hola%20mundo" in s.calls[0]


def test_callmebot_detects_error():
    s = FakeSession(FakeResp(200, "ERROR: APIKey is invalid"))
    assert CallMeBotNotifier("57300", "bad", session=s).send("x") is False


def _cal(start, prices):
    return {(start + timedelta(days=i)).isoformat(): float(p) for i, p in enumerate(prices)}


def test_digest_combines_feeder(config, history):
    start = date.today() + timedelta(days=10)
    history.record(RouteResult("BGA", "BOG", _cal(start - timedelta(days=1), [90_000, 95_000, 100_000])))
    history.record(RouteResult("BOG", "LIM", _cal(start, [500_000, 450_000])))
    history.record(RouteResult("MDE", "LIM", _cal(start, [430_000, 700_000])))  # sin feeder BGA-MDE
    rows = group_deals(config, config.group("Sudamérica"), history)
    lim = [r for r in rows if r.destination == "LIM"]
    assert len(lim) == 1
    # MDE 430k sin feeder gana frente a BOG 450k + feeder 95k = 545k
    assert lim[0].origin == "MDE" and lim[0].feeder_price is None
    history.record(RouteResult("BGA", "MDE", _cal(start - timedelta(days=1), [300_000, 300_000])))
    rows = group_deals(config, config.group("Sudamérica"), history)
    lim = [r for r in rows if r.destination == "LIM"][0]
    assert lim.origin == "BOG" and lim.total == 450_000 + 95_000


def test_build_digest_one_message_per_group(config, history):
    msgs = build_digest(config, history)
    assert len(msgs) == len(config.groups)
    assert all("Sin datos" in m for m in msgs)
