import pytest

from cheapflights.config import load_config

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
    assert "Resto de Colombia" not in names
    costa = config.zone("costa caribe")
    assert costa.kind == "domestic" and costa.origins == ("BGA",) and "CTG" in costa.destinations
    assert config.zone("Peru, Ecuador, Bolivia y Venezuela").origins == ("BOG", "MDE")
    assert config.zone("Europa").months_ahead == 9
    # los tramos desde casa se buscan tan lejos como los internacionales
    assert config.zone("Bogotá").months_ahead == 9 and config.zone("Medellín y Antioquia").months_ahead == 9


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


def test_feeder_must_cover_international_window(tmp_path):
    body = (
        "feeders: [{from: BGA, to: BOG}]\n"
        "zones:\n"
        "  - {name: A, kind: domestic, months_ahead: 6, destinations: {BOG: Bogotá}}\n"
        "  - {name: B, kind: international, months_ahead: 9, destinations: {LIM: Lima}}\n"
    )
    with pytest.raises(ValueError, match="months_ahead: 9"):
        load_config(_write(tmp_path, body))


def test_no_zones(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, "currency: COP\n"))


def test_quiet_hours_parsing(tmp_path):
    base = "zones:\n  - {name: A, destinations: {BOG: Bogotá}}\n"
    assert load_config(_write(tmp_path, base + "alerts: {quiet_hours: [23, 5]}\n")).alerts.quiet_hours == (23, 5)
    assert load_config(_write(tmp_path, base + "alerts: {quiet_hours: null}\n")).alerts.quiet_hours is None
