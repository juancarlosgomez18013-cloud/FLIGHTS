import json
from datetime import timedelta

from click.testing import CliRunner

from cheapflights.cli import cli, run_zones
from cheapflights.search import RateLimited, RouteResult

from .conftest import NOW, ROOT, TODAY, calendar


def _run(tmp_path, *args, env=None):
    runner = CliRunner()
    base = ["--config", str(ROOT / "config.yaml"), "--history", str(tmp_path / "h.json")]
    return runner.invoke(cli, base + list(args), env=env or {}, catch_exceptions=False)


class RealNotifier:
    """Finge un canal real (Telegram) que puede fallar en ciertos mensajes."""

    name = "Telegram"

    def __init__(self, fail_on=()):
        self.fail_on, self.sent = set(fail_on), []

    def send(self, text):
        self.sent.append(text)
        return len(self.sent) not in self.fail_on


def _searcher(prices_by_route):
    def search(origin, destination, start, end):
        return RouteResult(origin, destination, calendar(prices_by_route.get(f"{origin}-{destination}", [])))

    return search


DEALS = {
    "BGA-BOG": [60_000] + [124_000] * 40,
    "BGA-CTG": [70_000] + [250_000] * 40,
    "BGA-BAQ": [75_000] + [300_000] * 40,
    "BGA-PEI": [300_000] * 41,
}


def _zones(config):
    return [config.zone("Bogotá"), config.zone("Costa Caribe"), config.zone("Eje Cafetero")]


def test_super_alerts_once_then_again_only_if_cheaper_or_back(config, history, monkeypatch):
    monkeypatch.setattr("cheapflights.cli.is_real", lambda n: isinstance(n, RealNotifier))
    n = RealNotifier()
    r = run_zones(config, _zones(config), history, _searcher(DEALS), n, delay=0, now=NOW)
    assert sorted(v.destination for v in r.alerted) == ["BAQ", "BOG", "CTG"]
    assert len(n.sent) == 1 and n.sent[0].startswith("🔥 *3 vuelos súper baratos*")

    r = run_zones(config, _zones(config), history, _searcher(DEALS), n, delay=0, now=NOW + timedelta(hours=1))
    assert r.alerted == [] and r.already_alerted == 3 and len(n.sent) == 1

    gone = dict(DEALS, **{"BGA-BOG": [124_000] * 41})  # la oferta de Bogotá desaparece…
    run_zones(config, _zones(config), history, _searcher(gone), n, delay=0, now=NOW + timedelta(hours=2))
    back = run_zones(config, _zones(config), history, _searcher(DEALS), n, delay=0, now=NOW + timedelta(hours=3))
    assert [v.destination for v in back.alerted] == ["BOG"]  # …y vuelve: se avisa de nuevo


def test_failed_message_is_not_marked_as_sent(config, history, monkeypatch):
    monkeypatch.setattr("cheapflights.cli.is_real", lambda n: isinstance(n, RealNotifier))
    r = run_zones(config, _zones(config), history, _searcher(DEALS), RealNotifier(fail_on={1}), delay=0, now=NOW)
    assert r.alerted == [] and r.sent == (0, 1)
    assert history.data["alerts"] == {}  # se volverá a intentar en la próxima búsqueda


def test_without_real_channel_nothing_is_marked(config, history):
    from cheapflights.notify import ConsoleNotifier

    run_zones(config, _zones(config), history, _searcher(DEALS), ConsoleNotifier(), delay=0, now=NOW)
    assert history.data["alerts"] == {}


def test_rate_limit_keeps_what_was_already_searched(config, history):
    calls = []

    def search(origin, destination, start, end):
        calls.append(destination)
        if len(calls) == 3:
            raise RateLimited("HTTP 429")
        return RouteResult(origin, destination, calendar([200_000] * 10))

    from cheapflights.notify import ConsoleNotifier

    r = run_zones(config, [config.zone("Costa Caribe")], history, search, ConsoleNotifier(), delay=0, now=NOW)
    assert r.rate_limited and history.has_route("BGA-CTG") and history.has_route("BGA-BAQ")
    saved = json.loads(history.path.read_text())
    assert "BGA-BAQ" in saved["routes"]


def test_mock_end_to_end_cli(tmp_path):
    r = _run(tmp_path, "buscar", "--mock", "--dry-run", "--tipo", "todo")
    assert r.exit_code == 0, r.output
    assert "Bucaramanga → Bogotá" in r.output
    data = json.loads((tmp_path / "h.json").read_text())
    assert "BGA-BOG" in data["routes"] and "BOG-LIM" in data["routes"] and "BGA-EYP" in data["routes"]
    assert data["alerts"] == {}  # --dry-run no marca avisos
    for cmd in ("resumen", "plan", "probar"):
        r = _run(tmp_path, cmd, "--dry-run")
        assert r.exit_code == 0, r.output
    assert "Prueba" in r.output


def test_probar_without_channel_fails_loudly(tmp_path):
    r = _run(tmp_path, "probar")
    assert r.exit_code == 4
    assert "TELEGRAM_BOT_TOKEN" in r.output


def test_zonas_lists_city_names(tmp_path):
    r = _run(tmp_path, "zonas")
    assert r.exit_code == 0
    assert "Costa Caribe" in r.output and "Cartagena" in r.output and "Yopal" in r.output
