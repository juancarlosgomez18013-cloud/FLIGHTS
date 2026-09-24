import json
from datetime import timedelta

from click.testing import CliRunner

from cheapflights.cli import cli, run_zones
from cheapflights.search import RateLimited, RouteResult

from .conftest import NOW, ROOT, TODAY


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


def _searcher(prices_by_pair, calls=None):
    """Un precio por fecha de ida (desde mañana) para cada origen-destino; con maleta cuesta 50 % más."""
    base = TODAY + timedelta(days=1)

    def search(route, start, end):
        if calls is not None:
            calls.append((route.key, start, end))
        prices = prices_by_pair.get(route.pair, [])
        fares = {}
        d = start
        while d <= end:
            i = (d - base).days
            if 0 <= i < len(prices):
                fares[(d.isoformat(), (d + timedelta(days=route.nights[0])).isoformat())] = float(prices[i]) * (1.5 if route.bags else 1)
            d += timedelta(days=1)
        return RouteResult(route, fares)

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
    assert sorted(v.alert_key for v in r.alerted) == [
        "BAQ", "BOG", "CTG", "solo-ida:BGA-BAQ", "solo-ida:BGA-BOG", "solo-ida:BGA-CTG",
    ]
    assert len(n.sent) == 1 and n.sent[0].startswith("🔥 *6 vuelos súper baratos*")
    assert history.fares("BGA-BOG/2-5n/1m")  # se consultó la otra maleta alrededor de la oferta

    r = run_zones(config, _zones(config), history, _searcher(DEALS), n, delay=0, now=NOW + timedelta(hours=1))
    assert r.alerted == [] and r.already_alerted == 6 and len(n.sent) == 1

    gone = dict(DEALS, **{"BGA-BOG": [124_000] * 41})  # la oferta de Bogotá desaparece…
    run_zones(config, _zones(config), history, _searcher(gone), n, delay=0, now=NOW + timedelta(hours=2))
    back = run_zones(config, _zones(config), history, _searcher(DEALS), n, delay=0, now=NOW + timedelta(hours=3))
    assert sorted(v.alert_key for v in back.alerted) == ["BOG", "solo-ida:BGA-BOG"]  # …y vuelve: se avisa de nuevo


def test_other_bag_is_searched_only_around_the_deal(config, history):
    from cheapflights.notify import ConsoleNotifier

    calls = []
    run_zones(config, [config.zone("Bogotá")], history, _searcher(DEALS, calls), ConsoleNotifier(), delay=0, now=NOW)
    assert [c[0] for c in calls] == ["BGA-BOG/2-5n/0m", "BGA-BOG/ida/0m", "BOG-BGA/ida/0m", "BGA-BOG/2-5n/1m"]
    full, partial = calls[0], calls[3]
    assert (full[2] - full[1]).days + 1 == 180  # 6 meses de fechas de ida
    assert (partial[2] - partial[1]).days + 1 == 45 and partial[1] == full[1]  # una sola petición, alrededor de la oferta (mañana)
    assert history.is_partial("BGA-BOG/2-5n/1m") and not history.is_partial("BGA-BOG/2-5n/0m")
    assert history.fares("BGA-BOG/2-5n/1m")[((TODAY + timedelta(days=1)).isoformat(), (TODAY + timedelta(days=3)).isoformat())] == 90_000


def test_international_run_searches_the_home_connection_first(config, history):
    from cheapflights.notify import ConsoleNotifier

    calls = []
    prices = {"BGA-BOG": [100_000] * 300, "BGA-MDE": [90_000] * 300, "BOG-AUA": [500_000] + [900_000] * 60, "MDE-AUA": [950_000] * 61}
    run_zones(config, [config.zone("Islas del Caribe")], history, _searcher(prices, calls), ConsoleNotifier(), delay=0, now=NOW)
    keys = [c[0] for c in calls]
    assert keys[:2] == ["BGA-BOG/6-16n/1m", "BGA-MDE/6-16n/1m"]
    assert "BOG-AUA/6-14n/1m" in keys and "BOG-AUA/6-14n/0m" in keys
    assert history.best("BGA-BOG/6-16n/1m")["price"] == 150_000  # con maleta: 100.000 × 1,5


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

    def search(route, start, end):
        calls.append(route.destination)
        if len(calls) == 3:
            raise RateLimited("HTTP 429")
        return RouteResult(route, {((TODAY + timedelta(days=1)).isoformat(), (TODAY + timedelta(days=3)).isoformat()): 200_000.0})

    from cheapflights.notify import ConsoleNotifier

    r = run_zones(config, [config.zone("Costa Caribe")], history, search, ConsoleNotifier(), delay=0, now=NOW)
    assert r.rate_limited and history.has_route("BGA-CTG/2-5n/0m") and history.has_route("BGA-BAQ/2-5n/0m")
    assert len(calls) == 3  # tras el bloqueo no se sigue pidiendo (ni la otra maleta)
    saved = json.loads(history.path.read_text())
    assert "BGA-BAQ/2-5n/0m" in saved["routes"]


def test_mock_end_to_end_cli(tmp_path):
    r = _run(tmp_path, "buscar", "--mock", "--dry-run", "--tipo", "todo")
    assert r.exit_code == 0, r.output
    assert "Bucaramanga ⇄ Bogotá" in r.output and "noches" in r.output
    data = json.loads((tmp_path / "h.json").read_text())
    for key in ("BGA-BOG/2-5n/0m", "BOG-LIM/6-14n/1m", "BGA-EYP/2-5n/0m", "BGA-ADZ/3-7n/0m", "BGA-BOG/6-16n/1m"):
        assert key in data["routes"], key
    assert data["alerts"] == {}  # --dry-run no marca avisos
    for cmd in ("resumen", "plan", "probar"):
        r = _run(tmp_path, cmd, "--dry-run")
        assert r.exit_code == 0, r.output
    assert "Prueba" in r.output
    r = _run(tmp_path, "ver", "BGA-BOG")
    assert r.exit_code == 0 and "2-5 noches · sin maleta" in r.output and "6-16 noches · con maleta facturada" in r.output


def test_probar_without_channel_fails_loudly(tmp_path):
    r = _run(tmp_path, "probar")
    assert r.exit_code == 4
    assert "TELEGRAM_BOT_TOKEN" in r.output


def test_zonas_lists_city_names(tmp_path):
    r = _run(tmp_path, "zonas")
    assert r.exit_code == 0
    assert "Costa Caribe" in r.output and "Cartagena" in r.output and "Yopal" in r.output
    assert "2-5 noches" in r.output and "con maleta facturada" in r.output and "Conexión desde casa" in r.output


def test_armado_trip_wins_and_its_legs_are_not_alerted_twice(config, history, monkeypatch):
    monkeypatch.setattr("cheapflights.cli.is_real", lambda n: isinstance(n, RealNotifier))
    # ida y vuelta normal: $124.000 todos los días; ida suelta $20.000 un día y regreso $25.000 tres días después
    ida_day, back_day = TODAY + timedelta(days=5), TODAY + timedelta(days=8)

    def search(route, start, end):
        if not route.one_way:
            return _searcher({"BGA-BOG": [124_000] * 60})(route, start, end)
        cheap_day, price = (ida_day, 20_000.0) if route.pair == "BGA-BOG" else (back_day, 25_000.0)
        f = {((TODAY + timedelta(days=i)).isoformat(),) * 2: 90_000.0 for i in range(1, 60)}
        f[(cheap_day.isoformat(),) * 2] = price
        return RouteResult(route, f)

    n = RealNotifier()
    r = run_zones(config, [config.zone("Bogotá")], history, search, n, delay=0, now=NOW)
    assert [v.alert_key for v in r.alerted] == ["BOG"]  # un solo aviso: el viaje armado, sin repetir sus tramos
    assert r.alerted[0].legs == (20_000, 25_000) and r.alerted[0].price == 45_000
    assert "VIAJE ARMADO" in n.sent[0] and "🛫 Ida:" in n.sent[0]
    assert history.runs("BGA-BOG/2-5n/0m/armado")[-1]["min_price"] == 45_000
