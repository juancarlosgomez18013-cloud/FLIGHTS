from dataclasses import replace
from datetime import date, timedelta
from html.parser import HTMLParser

from cheapflights.config import LevelSettings
from cheapflights.levels import CHEAP, SUPER, classify, enrich
from cheapflights.messages import (
    MAX_VISIBLE_CHARS,
    Piece,
    best_month,
    fmt_date_long,
    fmt_date_short,
    fmt_price,
    fmt_trip_long,
    fmt_trip_short,
    format_alerts,
    format_alerts_packed,
    format_plan,
    format_summary,
    format_test,
    holiday_text,
    pack,
    visible_len,
)
from cheapflights.notify import to_plain, to_telegram_html
from cheapflights.search import RouteResult

from .conftest import NOW, TODAY, fares, route

LEVELS = LevelSettings()
ALLOWED_TELEGRAM_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre",
                         "span", "tg-spoiler", "blockquote", "tg-emoji"}


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


class TelegramHTMLChecker(HTMLParser):
    """Comprueba lo que exige parse_mode=HTML: solo etiquetas permitidas y bien cerradas."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TELEGRAM_TAGS:
            self.errors.append(f"etiqueta no permitida: {tag}")
        if tag == "a" and not dict(attrs).get("href", "").startswith("https://"):
            self.errors.append("enlace sin href https")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(f"cierre desordenado: {tag}")

    def handle_entityref(self, name):
        if name not in {"lt", "gt", "amp", "quot"}:
            self.errors.append(f"entidad no soportada: &{name};")


def assert_telegram_ok(markup: str):
    html_text = to_telegram_html(markup)
    checker = TelegramHTMLChecker()
    checker.feed(html_text)
    checker.close()
    assert not checker.errors, checker.errors
    assert not checker.stack, f"etiquetas sin cerrar: {checker.stack}"
    assert visible_len(markup) <= MAX_VISIBLE_CHARS < 4096


def test_formats_are_spanish_and_readable():
    assert fmt_price(1234567) == "$1.234.567"
    assert fmt_price(99.9, "USD") == "100 USD"
    assert fmt_date_long("2026-10-29", TODAY) == "jueves 29 de octubre"
    assert fmt_date_long("2027-01-20", TODAY) == "miércoles 20 de enero de 2027"
    assert fmt_date_short("2026-10-29", TODAY) == "jue 29 oct"
    assert fmt_date_short("2027-01-20", TODAY) == "mié 20 ene 2027"
    assert fmt_trip_short("2026-10-24", "2026-10-28", TODAY) == "sáb 24 → mié 28 oct"
    assert fmt_trip_short("2026-11-28", "2026-12-02", TODAY) == "sáb 28 nov → mié 2 dic"
    assert fmt_trip_short("2026-12-30", "2027-01-03", TODAY) == "mié 30 dic 2026 → dom 3 ene 2027"
    assert fmt_trip_long("2026-10-24", "2026-10-28", TODAY) == "sábado 24 de octubre → miércoles 28 de octubre · 4 noches"
    assert fmt_trip_long("2027-02-24", "2027-02-25", TODAY) == "miércoles 24 de febrero → jueves 25 de febrero de 2027 · 1 noche"


def test_holiday_text():
    assert holiday_text("2026-10-30", "2026-11-02", TODAY) == "🎉 Puente festivo: lun 2 nov (Todos los Santos)"
    assert holiday_text("2026-03-31", "2026-04-04", TODAY) == "🎉 Puente festivo: jue 2 abr (Jueves Santo) y vie 3 abr (Viernes Santo)"
    assert holiday_text("2026-12-06", "2026-12-09", TODAY) == "🎉 Festivo en el viaje: mar 8 dic (Inmaculada Concepción)"
    assert holiday_text("2026-10-13", "2026-10-16", TODAY) is None


def _super_domestic(config):
    zone = config.zone("Costa Caribe")
    v = classify(zone.route("BGA", "BAQ"), fares([98_958, 99_000] + [300_000] * 20 + [310_000] * 20), "COP", zone, LEVELS, [], TODAY)
    assert v.level == SUPER and v.bags == 0
    return v


def _super_international(config, history, other_bag=True):
    zone = config.zone("Perú, Ecuador, Bolivia y Venezuela")
    r = zone.route("BOG", "LIM")
    # la conexión sale de casa: un viaje por fecha de ida con 6 noches, igual que la oferta
    history.record(RouteResult(config.feeder_route("BOG", 1), fares([64_330] * 10, nights=(6, 16))), NOW)
    if other_bag:
        history.record(RouteResult(r.other_bags, {(_iso(2), _iso(8)): 250_000.0}), NOW, partial=True)
    v = classify(r, fares([600_000, 320_000] + [650_000] * 30, nights=(6, 14)), "COP", zone, LEVELS, [], TODAY)
    assert v.level == SUPER and v.bags == 1 and (v.out, v.back) == (_iso(2), _iso(8))
    return enrich(v, history, config, TODAY)


def test_one_or_two_alerts_use_detailed_cards(config, history):
    msgs = format_alerts(config, [_super_domestic(config), _super_international(config, history)], TODAY)
    assert len(msgs) == 1
    text = msgs[0]
    assert "🔥 *SÚPER BARATO* · 🏖️ Costa Caribe" in text
    assert "*Bucaramanga ⇄ Barranquilla*" in text and "ida y vuelta · sin maleta" in text
    assert "*Bogotá ⇄ Lima, Perú*" in text and "ida y vuelta · con maleta facturada" in text
    assert "🎒 Sin maleta: $250.000" in text  # el otro precio del mismo viaje
    assert "➕ Bucaramanga ⇄ Bogotá: $64.330" in text and "Total desde Bucaramanga: $384.330" in text
    assert "🗓️" in text and "2 noches" in text and "6 noches" in text
    assert "suele costar unos $" in text and "ahorras" in text and "Ver en Google Flights" in text
    assert "Mismo precio saliendo en 1 fecha más" in text
    assert "~" not in text and "Precio por persona" in text and "SOLO IDA" not in text
    assert "through" in text  # el enlace abre la búsqueda de ida y vuelta
    assert_telegram_ok(text)


def test_three_or_more_alerts_become_a_compact_list(config, history):
    many = [_super_domestic(config), _super_international(config, history)]
    zone = config.zone("Bogotá")
    many.append(classify(zone.route("BGA", "BOG"), fares([60_000] + [124_000] * 40), "COP", zone, LEVELS, [], TODAY))
    packed = format_alerts_packed(config, many, TODAY)
    text = packed[0][0]
    assert text.startswith("🔥 *3 viajes súper baratos*")
    assert "🇵🇪" in text  # bandera del país, no la de la zona
    assert "sin maleta" in text and "con maleta facturada · sin maleta: $250.000" in text
    assert sorted(v.destination for _, vs in packed for v in vs) == ["BAQ", "BOG", "LIM"]
    assert_telegram_ok(text)


def test_estimated_feeder_is_labelled(config, history):
    zone = config.zone("Perú, Ecuador, Bolivia y Venezuela")
    history.record(RouteResult(config.feeder_route("BOG", 1), fares([64_000] * 10, nights=(6, 16))), NOW)
    far = TODAY + timedelta(days=250)
    v = classify(zone.route("BOG", "LIM"), fares([320_000] + [650_000] * 20, start=far, nights=(6, 14)), "COP", zone, LEVELS, [], TODAY)
    v = enrich(v, history, config, TODAY)
    text = format_alerts(config, [v], TODAY)[0]
    assert "(aprox.)" in text and "Total desde Bucaramanga: unos $384.000" in text
    assert "Sin maleta" not in text  # no se buscó la otra maleta: no se inventa


def test_puente_shows_in_alert(config):
    zone = config.zone("Costa Caribe")
    f = {("2026-10-30", "2026-11-02"): 150_000.0} | {(d, b): 400_000.0 for d, b in fares([1] * 40)}
    v = classify(zone.route("BGA", "CTG"), f, "COP", zone, LEVELS, [], TODAY)
    text = format_alerts(config, [v], TODAY)[0]
    assert "🎉 Puente festivo: lun 2 nov (Todos los Santos)" in text
    assert "viernes 30 de octubre → lunes 2 de noviembre · 3 noches" in text


def test_summary_sections_and_telegram_html(config, history):
    dom = _super_domestic(config)
    zone = config.zone("Amazonas")
    cheap = classify(zone.route("BGA", "LET"), fares([418_700] * 3 + [560_000] * 7), "COP", zone, LEVELS, [], TODAY)
    assert cheap.level == CHEAP
    intl = _super_international(config, history)
    msgs = format_summary(config, {"domestic": [dom, cheap], "international": [intl]}, TODAY)
    text = "\n\n".join(msgs)
    assert "☀️ *Viajes baratos de hoy*" in text
    assert "🇨🇴 *COLOMBIA* · desde Bucaramanga" in text
    assert "✈️ *INTERNACIONAL* · desde Bogotá o Medellín" in text
    assert text.index("🔥 *Súper barato*") < text.index("👍 *Barato*")
    assert "Leticia" in text and "Lima, Perú" in text and "sale de Bogotá" in text and "con la conexión desde Bucaramanga" in text
    for m in msgs:
        assert_telegram_ok(m)


def test_summary_empty_and_stale(config):
    msgs = format_summary(config, {"domestic": [], "international": []}, TODAY, {"domestic": None, "international": 5})
    text = msgs[0]
    assert "Aún no hay datos" in text
    assert "Hace 5 días que no llegan precios nuevos" in text


def test_summary_can_skip_when_empty(config):
    cfg = replace(config, summary=replace(config.summary, send_when_empty=False))
    assert format_summary(cfg, {"domestic": [], "international": []}, TODAY) == []


def test_summary_limits_items_per_section(config):
    zone = config.zone("Costa Caribe")
    many = [classify(zone.route("BGA", d), fares([50_000 + i] + [300_000] * 30), "COP", zone, LEVELS, [], TODAY)
            for i, d in enumerate(["CTG", "BAQ", "SMR", "RCH", "VUP", "MTR"] * 2)]
    cfg = replace(config, summary=replace(config.summary, max_per_section=3))
    text = format_summary(cfg, {"domestic": many}, TODAY)[0]
    assert "…y 9 destinos más" in text


def test_long_summary_never_splits_a_destination(config):
    zone = config.zone("Europa")
    items = [classify(zone.route("BOG", d), fares([900_000 + i] + [2_000_000] * 30, nights=(6, 14)), "COP", zone, LEVELS, [], TODAY)
             for i, d in enumerate(zone.destinations * 4)]
    cfg = replace(config, summary=replace(config.summary, max_per_section=40))
    msgs = format_summary(cfg, {"international": items}, TODAY)
    assert len(msgs) >= 2
    for m in msgs[1:]:
        first = m.split("\n")[0]
        assert first.startswith("✈️ *INTERNACIONAL*") and "(sigue)" in first
        assert m.split("\n")[1] in ("🔥 *Súper barato*", "👍 *Barato*")
    for m in msgs:
        assert_telegram_ok(m)


def test_plan_and_best_month(config):
    f = {}
    d = date(2026, 10, 1)
    while d < date(2027, 1, 1):
        for n in (2, 3):  # varias vueltas por ida: se cuentan fechas de ida, no combinaciones
            f[(d.isoformat(), (d + timedelta(days=n)).isoformat())] = 100_000 if (d.month == 11 and d.day % 2) else 200_000
        d += timedelta(days=1)
    f[("2026-10-02", "2026-10-04")] = 90_000
    assert best_month(f, 120_000, TODAY) == ("noviembre", 15)
    assert best_month({("2026-09-28", "2026-09-30"): 1.0, ("2026-10-10", "2026-10-12"): 1.0}, 5, TODAY) == ("octubre", 1)  # sep casi termina
    zone = config.zone("Bogotá")
    v = classify(zone.route("BGA", "BOG"), f, "COP", zone, LEVELS, [], TODAY)
    text = format_plan(config, {"domestic": [(v, ("noviembre", 15))], "international": []}, TODAY)[0]
    assert "🏙️ *Bogotá*: $90.000 · vie 2 → dom 4 oct (2 noches, sin maleta)" in text  # no repite "Bogotá Bogotá"
    assert "Más fechas baratas en noviembre (15 días de salida)" in text
    assert_telegram_ok(text)


def test_test_message(config):
    text = format_test(config, _super_domestic(config), TODAY)[0]
    assert "Prueba" in text and "SÚPER BARATO" in text and "apenas lo encuentro" in text and "ida y vuelta" in text
    assert_telegram_ok(text)


def test_pack_measures_visible_text_and_repeats_context():
    link = "[x](https://www.google.com/travel/flights?" + "q" * 300 + ")"
    pieces = [Piece(f"línea {i} {link}", context="ENCABEZADO (sigue)") for i in range(400)]
    msgs = pack(pieces, limit=500, footer="pie")
    assert all(visible_len(t) <= 500 for t, _ in msgs)
    assert all(t.startswith("ENCABEZADO (sigue)") for t, _ in msgs[1:])
    assert msgs[-1][0].endswith("pie")
    assert len(msgs[0][0]) > 500  # las URL no cuentan: caben muchas más líneas


def test_plain_rendering_for_whatsapp():
    markup = "• *[Bogotá](https://g.co/a?b=1&c=2)*: $1\n[👉 Ver en Google Flights](https://g.co/x?y=1)"
    assert to_plain(markup) == "• *Bogotá*: $1\n👉 Ver en Google Flights: https://g.co/x?y=1"
    assert to_plain(markup, inline_urls=True) == (
        "• *Bogotá*: $1\n   👉 https://g.co/a?b=1&c=2\n👉 Ver en Google Flights: https://g.co/x?y=1"
    )
    assert "*" not in to_plain(markup, keep_bold=False)


def test_one_way_alert_and_link(config):
    zone = config.zone("Costa Caribe")
    r = route("CTG", "BGA", (0, 0))
    v = classify(r, {(d, d): p for (d, _), p in fares([55_000] + [180_000] * 40).items()}, "COP", zone, LEVELS, [], TODAY)
    assert v.one_way and v.level == SUPER and v.alert_key == "solo-ida:CTG-BGA" and v.out == v.back
    text = format_alerts(config, [v], TODAY)[0]
    assert "🔥 *SÚPER BARATO · SOLO IDA* · 🏖️ Costa Caribe" in text
    assert "*Cartagena → Bucaramanga*" in text and "*$55.000* solo ida · sin maleta" in text
    assert "noches" not in text and "one+way" in text
    assert_telegram_ok(text)


def test_split_price_line_and_summary_one_way_section(config):
    zone = config.zone("Costa Caribe")
    rt = classify(zone.route("BGA", "BAQ"), fares([98_958, 99_000] + [300_000] * 40), "COP", zone, LEVELS, [], TODAY)
    rt = replace(rt, split_price=80_000.0)
    text = format_alerts(config, [rt], TODAY)[0]
    assert "✂️ Armado con dos tramos solo ida: $80.000 (ahorras $18.958)" in text
    ow = classify(route("BGA", "CTG", (0, 0)), {(d, d): p for (d, _), p in fares([50_000] + [180_000] * 40).items()}, "COP", zone, LEVELS, [], TODAY)
    msgs = format_summary(config, {"domestic": [rt, ow]}, TODAY)
    text = "\n".join(msgs)
    assert text.index("🔥 *Súper barato*") < text.index("🎫 *Solo ida*")
    assert "• 🔥 🏖️ *[Bucaramanga → Cartagena]" in text and "solo ida · sin maleta" in text
    assert "armado con dos tramos solo ida: $80.000" in text
    for m in msgs:
        assert_telegram_ok(m)
