from datetime import date

from cheapflights.festivos import es_puente, festivos, festivos_en, pascua


def test_festivos_2026_match_the_official_calendar():
    expected = {
        date(2026, 1, 1), date(2026, 1, 12), date(2026, 3, 23), date(2026, 4, 2), date(2026, 4, 3),
        date(2026, 5, 1), date(2026, 5, 18), date(2026, 6, 8), date(2026, 6, 15), date(2026, 6, 29),
        date(2026, 7, 20), date(2026, 8, 7), date(2026, 8, 17), date(2026, 10, 12), date(2026, 11, 2),
        date(2026, 11, 16), date(2026, 12, 8), date(2026, 12, 25),
    }
    assert set(festivos(2026)) == expected
    assert festivos(2026)[date(2026, 11, 2)] == "Todos los Santos"


def test_festivos_2027_moved_to_monday_and_easter_based():
    assert pascua(2027) == date(2027, 3, 28)
    f = festivos(2027)
    assert date(2027, 1, 11) in f  # Reyes (6 de enero, miércoles) pasa al lunes
    assert date(2027, 3, 25) in f and date(2027, 3, 26) in f  # Semana Santa
    assert date(2027, 5, 10) in f and date(2027, 5, 31) in f and date(2027, 6, 7) in f
    assert date(2027, 11, 15) in f and date(2027, 11, 1) in f
    assert all(d.weekday() == 0 for d in (date(2027, 1, 11), date(2027, 5, 10), date(2027, 11, 15)))
    assert len(f) == 18


def test_festivos_in_trip_and_puente():
    assert festivos_en("2026-10-30", "2026-11-02") == [(date(2026, 11, 2), "Todos los Santos")]
    assert es_puente("2026-10-30", "2026-11-02")
    assert not es_puente("2026-12-06", "2026-12-09")  # 8 de diciembre de 2026 cae martes
    assert festivos_en("2026-10-13", "2026-10-16") == []
    assert [d for d, _ in festivos_en("2026-12-30", "2027-01-12")] == [date(2027, 1, 1), date(2027, 1, 11)]
