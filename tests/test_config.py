import pytest

from cheapflights.config import load_config
from cheapflights.search import Route

# Palabra que debe aparecer en el nombre oficial del aeropuerto (según fli) para cada código.
# Así se detecta un código que existe pero es de otro lugar (ej. YOP = Rainbow Lake, Canadá).
AIRPORT_KEYWORDS = {
    "BGA": "Palonegro", "BOG": "Dorado", "MDE": "Cordova", "EOH": "Olaya", "APO": "Antonio Roldan",
    "CTG": "Rafael Nunez", "BAQ": "Cortissoz", "SMR": "Simon Bolivar", "RCH": "Almirante Padilla",
    "VUP": "Alfonso Lopez", "MTR": "Garzones", "ADZ": "Gustavo Rojas", "PEI": "Matecana",
    "AXM": "Eden", "MZL": "Nubia", "CLO": "Bonilla Aragon", "UIB": "Carano", "PPN": "Guillermo Leon",
    "PSO": "Narino", "CUC": "Camilo Daza", "AUC": "Santiago Perez", "EYP": "Yopal",
    "VVC": "Vanguardia", "IBE": "Perales", "NVA": "Benito Salas", "FLA": "Artunduaga",
    "LET": "Vasquez Cobo",
}


def test_real_config_zones(config):
    assert config.home == "BGA"
    names = [z.name for z in config.zones]
    for expected in ["Bogotá", "Costa Caribe", "Eje Cafetero", "Brasil", "Europa"]:
        assert expected in names
    costa = config.zone("costa caribe")
    assert costa.kind == "domestic" and costa.origins == ("BGA",) and "CTG" in costa.destinations
    assert costa.nights == (2, 5) and costa.bags == 0 and costa.months_ahead == 6
    europa = config.zone("Europa")
    assert europa.origins == ("BOG", "MDE") and europa.months_ahead == 9
    assert europa.nights == (6, 14) and europa.bags == 1
    assert config.zone("San Andrés").nights == (3, 7)  # ajuste por zona
    assert costa.one_way and europa.one_way and len(europa.one_way_routes()) == 2 * 2 * 9  # 2 hubs × 9 destinos × 2 sentidos
    assert costa.one_way_routes()[:2] == [Route("BGA", "CTG", (0, 0), 0), Route("CTG", "BGA", (0, 0), 0)]
    assert Route("BGA", "CTG", (0, 0), 0).key == "BGA-CTG/ida/0m"
    assert costa.route("BGA", "CTG") == Route("BGA", "CTG", (2, 5), 0)
    assert costa.searches(True)[:2] == [Route("BGA", "CTG", (2, 5), 0), Route("BGA", "CTG", (2, 5), 1)]
    assert all(r.bags == 0 for r in costa.searches(False))


def test_feeders_follow_the_international_trip(config):
    assert config.feeder_nights == (6, 16) and config.feeder_months == 9
    assert config.feeder_searches() == [Route("BGA", "BOG", (6, 16), 1), Route("BGA", "MDE", (6, 16), 1)]
    assert config.feeder_route("MDE", 0) == Route("BGA", "MDE", (6, 16), 0)
    assert config.feeder_route("BGA", 1) is None and config.feeder_route("CLO", 1) is None


def test_every_destination_has_a_city_name(config):
    for z in config.zones:
        assert z.emoji, z.name
        for d in z.destinations:
            assert config.city(d) != d, f"{d} sin nombre de ciudad"
    for code in ("BGA", "BOG", "MDE"):
        assert config.city(code) != code


def test_colombian_codes_are_the_right_airports(config):
    from fli.models import Airport

    for z in config.zones:
        for code in z.origins + z.destinations:
            Airport[code]  # existe en la librería de Google Flights
            if code in AIRPORT_KEYWORDS:
                assert AIRPORT_KEYWORDS[code].lower() in Airport[code].value.lower(), (code, Airport[code].value)
    assert "YOP" not in [d for z in config.zones for d in z.destinations]


def test_zone_lookup_ignores_accents_and_case(config):
    assert config.zone("BOGOTA").name == "Bogotá"
    with pytest.raises(KeyError):
        config.zone("Resto de Colombia")


def _write(tmp_path, body):
    p = tmp_path / "c.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_optional_fixed_prices_per_destination(tmp_path):
    body = (
        "zones:\n"
        "  - name: Costa\n"
        "    super_barato: 90000\n"
        "    barato: 120000\n"
        "    destinations:\n"
        "      CTG: {ciudad: Cartagena, super_barato: 70000, barato: 100000}\n"
        "      BAQ: Barranquilla\n"
    )
    c = load_config(_write(tmp_path, body))
    z = c.zone("Costa")
    assert z.fixed_prices("CTG") == (70000, 100000)
    assert z.fixed_prices("BAQ") == (90000, 120000)
    assert c.city("CTG") == "Cartagena"
    c2 = load_config(_write(tmp_path, "zones:\n  - {name: X, destinations: {BOG: Bogotá}}\n"))
    assert c2.zone("X").fixed_prices("BOG") == (None, None)


def test_nights_and_bags_defaults_and_overrides(tmp_path):
    body = (
        "nights: {domestic: [3, 4], international: 7}\n"
        "bags: {domestic: true}\n"
        "feeders: [{from: BGA, to: BOG}, {from: BGA, to: MDE}]\n"
        "zones:\n"
        "  - {name: A, destinations: {CTG: Cartagena}}\n"
        "  - {name: B, nights: [1, 2], bags: no, one_way: false, destinations: {CLO: Cali}}\n"
        "  - {name: C, kind: international, destinations: {LIM: Lima}}\n"
    )
    c = load_config(_write(tmp_path, body))
    assert (c.zone("A").nights, c.zone("A").bags) == ((3, 4), 1)
    assert (c.zone("B").nights, c.zone("B").bags) == ((1, 2), 0)
    assert c.zone("A").one_way and not c.zone("B").one_way and c.zone("C").one_way
    assert (c.zone("C").nights, c.zone("C").bags) == ((7, 7), 1)  # un número = esa duración exacta; internacional con maleta
    assert c.feeder_nights == (7, 9)
    for bad in ("nights: {domestic: [5, 2]}\n", "nights: {domestic: [0, 3]}\n", "bags: {domestic: quizás}\n"):
        with pytest.raises(ValueError):
            load_config(_write(tmp_path, bad + "zones:\n  - {name: A, destinations: {CTG: Cartagena}}\n"))


def test_super_must_be_below_cheap(tmp_path):
    p = _write(tmp_path, "zones:\n  - name: X\n    destinations:\n      BOG: {ciudad: B, super_barato: 200, barato: 100}\n")
    with pytest.raises(ValueError, match="menor"):
        load_config(p)


def test_invalid_iata(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, "zones:\n  - name: X\n    destinations: [BOGOTA]\n"))


def test_duplicate_destination_in_same_kind(tmp_path):
    body = "zones:\n  - {name: A, destinations: {BOG: Bogotá}}\n  - {name: B, destinations: {BOG: Bogotá}}\n"
    with pytest.raises(ValueError, match="repetidos"):
        load_config(_write(tmp_path, body))


def test_international_origins_need_a_feeder(tmp_path):
    body = "zones:\n  - {name: B, kind: international, destinations: {LIM: Lima}}\n"
    with pytest.raises(ValueError, match="conexión desde BGA hacia BOG, MDE"):
        load_config(_write(tmp_path, body))
    with pytest.raises(ValueError, match="salir de casa"):
        load_config(_write(tmp_path, "feeders: [{from: BOG, to: MDE}]\n" + body))


def test_no_zones(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, "currency: COP\n"))


def test_quiet_hours_parsing(tmp_path):
    base = "zones:\n  - {name: A, destinations: {BOG: Bogotá}}\n"
    assert load_config(_write(tmp_path, base + "alerts: {quiet_hours: [23, 5]}\n")).alerts.quiet_hours == (23, 5)
    assert load_config(_write(tmp_path, base + "alerts: {quiet_hours: null}\n")).alerts.quiet_hours is None
