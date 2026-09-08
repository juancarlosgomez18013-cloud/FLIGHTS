import pytest

from cheapflights.config import load_config


def test_loads_real_config(config):
    assert config.home == "BGA"
    assert config.currency == "COP"
    names = {g.name for g in config.groups}
    assert {"Colombia", "Sudamérica", "Europa"} <= names
    assert config.group("colombia").kind == "domestic"
    assert all(len(d) == 3 for g in config.groups for d in g.destinations)
    assert {(f.origin, f.destination) for f in config.feeders} == {("BGA", "BOG"), ("BGA", "MDE")}


def test_routes_skip_same_airport(config):
    g = config.group("Colombia")
    assert ("BGA", "BGA") not in g.routes()
    assert ("BGA", "BOG") in g.routes()


def test_invalid_iata(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("groups:\n  - name: x\n    destinations: [BOGOTA]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(p)


def test_no_groups(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("currency: COP\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(p)
