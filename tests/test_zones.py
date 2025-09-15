# tests/test_zones.py
from bot_core.indicators import aggregate_swings_to_zones

def test_aggregate_swings_groups_close_prices():
    swings = [
        {"index": 5, "price": 1.0000, "type": "resistance"},
        {"index": 8, "price": 1.0008, "type": "resistance"},
        {"index": 12, "price": 1.0200, "type": "resistance"},
        {"index": 7, "price": 0.9800, "type": "support"},
        {"index": 14, "price": 0.9810, "type": "support"},
    ]
    # tolerance 0.001 (0.1%) groups the first two resistances and the two supports
    zones = aggregate_swings_to_zones(swings, price_tolerance=0.001, min_points=1)
    # zones must contain both types
    assert any(z["type"] == "resistance" for z in zones)
    assert any(z["type"] == "support" for z in zones)
    # check a resistance zone was formed with count >= 2
    res_zones = [z for z in zones if z["type"] == "resistance"]
    assert any(z["count"] >= 2 for z in res_zones)
    # check support zone count >= 2
    sup_zones = [z for z in zones if z["type"] == "support"]
    assert any(z["count"] >= 2 for z in sup_zones)

def test_zone_fields_and_strength():
    swings = [
        {"index": 1, "price": 10.0, "type": "resistance"},
        {"index": 2, "price": 10.02, "type": "resistance"},
    ]
    zones = aggregate_swings_to_zones(swings, price_tolerance=0.005)
    assert len(zones) >= 1
    z = zones[0]
    # fields present
    assert set(["center", "min_price", "max_price", "count", "indices", "strength"]).issubset(set(z.keys()))
    assert z["count"] == 2
    assert z["strength"] > 0.0
