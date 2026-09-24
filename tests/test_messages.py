from datetime import date, timedelta
from html.parser import HTMLParser

from cheapflights.config import LevelSettings
from cheapflights.levels import CHEAP, SUPER, classify, with_feeder
from cheapflights.messages import (
    MAX_VISIBLE_CHARS,
    Piece,
    best_month,
    format_alerts_packed,
    pack,
    visible_len,
    fmt_date_long,
    fmt_date_short,
    fmt_price,
    format_alerts,
    format_plan,
    format_summary,
    format_test,
)
from cheapflights.notify import to_plain, to_telegram_html

from .conftest import NOW, TODAY, calendar, make_result

LEVELS = LevelSettings()
ALLOWED_TELEGRAM_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre",
                         "span", "tg-spoiler", "blockquote", "tg-emoji"}


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


def _super_domestic(config):
    zone = config.zone("Costa Caribe")
    cal = calendar([98_958, 99_000] + [300_000] * 20 + [310_000] * 20)
    v = classify("BGA", "BAQ", cal, "COP", zone, LEVELS, [], TODAY)
    assert v.level == SUPER
    return v


def _super_international(config, history):
    history.record(make_result("BGA", "BOG", [64_330] * 10), NOW)
    zone = config.zone("Perú, Ecuador, Bolivia y Venezuela")
    v = classify("BOG", "LIM", calendar([600_000, 320_000] + [650_000] * 30), "COP", zone, LEVELS, [], TODAY)
    assert v.level == SUPER
    return with_feeder(v, history, "BGA", TODAY)


def test_one_or_two_alerts_use_detailed_cards(config, history):
    msgs = format_alerts(config, [_super_domestic(config), _super_international(config, history)], TODAY)
    assert len(msgs) == 1
    text = msgs[0]
    assert "🔥 *SÚPER BARATO* · 🏖️ Costa Caribe" in text
    assert "*Bucaramanga → Barranquilla*" in text
    assert "*Bogotá → Lima, Perú*" in text
    assert "Total desde Bucaramanga: $384.330" in text
    assert "suele costar unos $" in text and "ahorras" in text and "Ver en Google Flights" in text
    assert "Mismo precio en 1 fecha más" in text
    assert "~" not in text and "Solo ida" in text
    assert_telegram_ok(text)


def test_three_or_more_alerts_become_a_compact_list(config, history):
    many = [_super_domestic(config), _super_international(config, history)]
    zone = config.zone("Bogotá")
    many.append(classify("BGA", "BOG", calendar([60_000] + [124_000] * 40), "COP", zone, LEVELS, [], TODAY))
    packed = format_alerts_packed(config, many, TODAY)
    text = packed[0][0]
    assert text.startswith("🔥 *3 vuelos súper baratos*")
    assert "🇵🇪" in text  # bandera del país, no la de la zona
    assert sorted(v.destination for _, vs in packed for v in vs) == ["BAQ", "BOG", "LIM"]
    assert_telegram_ok(text)


def test_estimated_feeder_is_labelled(config, history):
    history.record(make_result("BGA", "BOG", [64_000] * 10), NOW)
    zone = config.zone("Perú, Ecuador, Bolivia y Venezuela")
    far = TODAY + timedelta(days=250)
    v = classify("BOG", "LIM", calendar([320_000] + [650_000] * 20, start=far), "COP", zone, LEVELS, [], TODAY)
    v = with_feeder(v, history, "BGA", TODAY)
    text = format_alerts(config, [v], TODAY)[0]
    assert "(aprox.)" in text and "Total desde Bucaramanga: unos $384.000" in text


def test_summary_sections_and_telegram_html(config, history):
    dom = _super_domestic(config)
    cheap = classify("BGA", "LET", calendar([418_700] * 3 + [560_000] * 7), "COP", config.zone("Amazonas"), LEVELS, [], TODAY)
    assert cheap.level == CHEAP
    intl = _super_international(config, history)
    msgs = format_summary(config, {"domestic": [dom, cheap], "international": [intl]}, TODAY)
    text = "\n\n".join(msgs)
    assert "☀️ *Vuelos baratos de hoy*" in text
    assert "🇨🇴 *COLOMBIA* · desde Bucaramanga" in text
    assert "✈️ *INTERNACIONAL* · desde Bogotá o Medellín" in text
    assert text.index("🔥 *Súper barato*") < text.index("👍 *Barato*")
    assert "Leticia" in text and "Lima, Perú" in text and "sale de Bogotá" in text
    for m in msgs:
        assert_telegram_ok(m)


def test_summary_empty_and_stale(config):
    msgs = format_summary(config, {"domestic": [], "international": []}, TODAY, {"domestic": None, "international": 5})
    text = msgs[0]
    assert "Aún no hay datos" in text
    assert "Hace 5 días que no llegan precios nuevos" in text


def test_summary_can_skip_when_empty(config):
    from dataclasses import replace

    cfg = replace(config, summary=replace(config.summary, send_when_empty=False))
    assert format_summary(cfg, {"domestic": [], "international": []}, TODAY) == []


def test_summary_limits_items_per_section(config):
    zone = config.zone("Costa Caribe")
    many = [classify("BGA", d, calendar([50_000 + i] + [300_000] * 30), "COP", zone, LEVELS, [], TODAY)
            for i, d in enumerate(["CTG", "BAQ", "SMR", "RCH", "VUP", "MTR"] * 2)]
    from dataclasses import replace

    cfg = replace(config, summary=replace(config.summary, max_per_section=3))
    text = format_summary(cfg, {"domestic": many}, TODAY)[0]
    assert "…y 9 destinos más" in text


def test_long_summary_never_splits_a_destination(config):
    from dataclasses import replace

    zone = config.zone("Europa")
    items = [classify("BOG", d, calendar([900_000 + i] + [2_000_000] * 30), "COP", zone, LEVELS, [], TODAY)
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
    cal = {}
    d = date(2026, 10, 1)
    while d < date(2027, 1, 1):
        cal[d.isoformat()] = 100_000 if (d.month == 11 and d.day % 2) else 200_000
        d += timedelta(days=1)
    cal["2026-10-02"] = 90_000
    assert best_month(cal, 120_000, TODAY) == ("noviembre", 15)
    assert best_month({"2026-09-28": 1.0, "2026-10-10": 1.0}, 5, TODAY) == ("octubre", 1)  # sep casi termina
    zone = config.zone("Bogotá")
    v = classify("BGA", "BOG", cal, "COP", zone, LEVELS, [], TODAY)
    text = format_plan(config, {"domestic": [(v, ("noviembre", 15))], "international": []}, TODAY)[0]
    assert "🏙️ *Bogotá*: $90.000" in text  # no repite "Bogotá Bogotá"
    assert "Más fechas baratas en noviembre (15 días)" in text
    assert_telegram_ok(text)


def test_test_message(config):
    text = format_test(config, _super_domestic(config), TODAY)[0]
    assert "Prueba" in text and "SÚPER BARATO" in text and "apenas lo encuentro" in text
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
