"""Tests for src/services/reports/geo.py — no network, Overpass is mocked."""

from __future__ import annotations

import pytest
import requests

from src.services.reports import geo
from src.services.reports.geo import PoiCounts, _parse_counts, location_score


def _count_payload(totals: list[int]) -> dict:
    return {
        "elements": [
            {"type": "count", "tags": {"total": str(t), "nodes": str(t)}} for t in totals
        ]
    }


def test_parse_counts_positional_order():
    counts = _parse_counts(_count_payload([9, 4, 3, 2, 25, 6, 30, 11, 120]))
    assert counts == PoiCounts(
        transport_500m=9,
        grocery_500m=4,
        schools_1km=3,
        parks_1km=2,
        restaurants_1km=25,
        healthcare_1km=6,
        transport_1km=30,
        grocery_1km=11,
        transport_3km=120,
    )


def test_parse_counts_rejects_wrong_shape():
    assert _parse_counts({"elements": []}) is None
    assert _parse_counts(_count_payload([1, 2, 3])) is None  # too few counts
    # Non-count elements (e.g. remarks) are ignored, not miscounted.
    payload = _count_payload([1] * 9)
    payload["elements"].insert(0, {"type": "node", "id": 1})
    assert _parse_counts(payload) is not None


def test_location_score_bounds_and_monotonicity():
    empty = PoiCounts(0, 0, 0, 0, 0, 0, 0, 0, 0)
    dense = PoiCounts(50, 20, 10, 8, 60, 20, 120, 40, 500)
    assert location_score(empty) == 0
    assert location_score(dense) == 100
    mid = PoiCounts(4, 2, 2, 1, 8, 4, 10, 5, 40)
    assert 0 < location_score(mid) < 100
    better = PoiCounts(6, 2, 2, 1, 8, 4, 10, 5, 40)
    assert location_score(better) > location_score(mid)


def test_fetch_returns_none_on_network_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("overpass down")

    monkeypatch.setattr(geo.requests, "post", boom)
    monkeypatch.setattr(geo, "_cache", {})
    assert geo.fetch_poi_counts(50.08, 14.43) is None


def test_fetch_caches_successful_lookups(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return _count_payload([1, 2, 3, 4, 5, 6, 7, 8, 9])

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        return FakeResponse()

    monkeypatch.setattr(geo.requests, "post", fake_post)
    monkeypatch.setattr(geo, "_cache", {})
    first = geo.fetch_poi_counts(50.08, 14.43)
    second = geo.fetch_poi_counts(50.08, 14.43)
    assert first == second
    assert first is not None and first.transport_500m == 1
    assert calls["n"] == 1  # second hit served from the cache


def test_poi_counts_to_location_fields_maps_all_names():
    counts = PoiCounts(
        transport_500m=1, grocery_500m=2, schools_1km=3, parks_1km=4,
        restaurants_1km=5, healthcare_1km=6, transport_1km=7, grocery_1km=8,
        transport_3km=9,
    )
    fields = geo.poi_counts_to_location_fields(counts)
    assert fields == {
        "nearby_transport_count_500m": 1,
        "nearby_grocery_count_500m": 2,
        "nearby_schools_count_1km": 3,
        "nearby_parks_count_1km": 4,
        "nearby_restaurants_count_1km": 5,
        "nearby_healthcare_count_1km": 6,
        "nearby_transport_count_1km": 7,
        "nearby_grocery_count_1km": 8,
        "nearby_transport_count_3km": 9,
    }


def test_build_query_has_one_count_per_category():
    query = geo._build_query(50.08, 14.43)
    assert query.count("out count;") == 9
    assert "around:3000" in query and "around:500" in query


# --- nearest named facilities ----------------------------------------------- #

_LAT, _LON = 50.08, 14.43


def _node(name, tags, dlat=0.0, dlon=0.0, id=1):
    return {
        "type": "node", "id": id, "lat": _LAT + dlat, "lon": _LON + dlon,
        "tags": {"name": name, **tags} if name else dict(tags),
    }


def test_build_pois_query_one_out_per_category_named_only():
    query = geo._build_pois_query(_LAT, _LON)
    assert query.count("out tags center") == len(geo._POI_CATEGORIES)
    assert '["name"]' in query
    assert "out count" not in query


def test_parse_nearest_pois_picks_closest_per_category_in_display_order():
    payload = {"elements": [
        _node("Far Cafe", {"amenity": "cafe"}, dlat=0.008, id=1),
        _node("Near Cafe", {"amenity": "cafe"}, dlat=0.001, id=2),
        _node("Albert", {"shop": "supermarket"}, dlon=0.002, id=3),
        _node("Anděl", {"railway": "tram_stop"}, dlat=0.002, id=4),
        _node(None, {"amenity": "restaurant"}, id=5),          # unnamed → skipped
        _node("Random Office", {"office": "it"}, id=6),        # unclassified → skipped
    ]}
    pois = geo._parse_nearest_pois(payload, _LAT, _LON)
    assert [(p.category, p.name) for p in pois] == [
        ("transport", "Anděl"), ("grocery", "Albert"), ("restaurants", "Near Cafe"),
    ]
    # 0.001° latitude ≈ 111 m
    near_cafe = pois[-1]
    assert 100 <= near_cafe.distance_m <= 125


def test_parse_nearest_pois_uses_center_for_ways():
    payload = {"elements": [{
        "type": "way", "id": 9,
        "center": {"lat": _LAT + 0.002, "lon": _LON},
        "tags": {"name": "Sady Na Skalce", "leisure": "park"},
    }]}
    pois = geo._parse_nearest_pois(payload, _LAT, _LON)
    assert len(pois) == 1 and pois[0].category == "parks"


def test_fetch_nearest_pois_returns_none_on_network_failure(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("overpass down")

    monkeypatch.setattr(geo.requests, "post", boom)
    monkeypatch.setattr(geo, "_pois_cache", {})
    monkeypatch.setattr(geo.config, "LOCATION_POI_CACHE_DIR", str(tmp_path))
    assert geo.fetch_nearest_pois(_LAT, _LON) is None
    assert list(tmp_path.iterdir()) == []  # failures are never cached


def test_fetch_nearest_pois_disk_cache_survives_process_restart(monkeypatch, tmp_path):
    calls = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"elements": [_node("Albert", {"shop": "supermarket"}, dlon=0.002)]}

    def counting_post(*args, **kwargs):
        calls["n"] += 1
        return FakeResponse()

    monkeypatch.setattr(geo.requests, "post", counting_post)
    monkeypatch.setattr(geo.config, "LOCATION_POI_CACHE_DIR", str(tmp_path))

    monkeypatch.setattr(geo, "_pois_cache", {})
    first = geo.fetch_nearest_pois(_LAT, _LON)
    assert calls["n"] == 1
    assert first and first[0].name == "Albert"

    # A fresh process (empty in-memory cache) reads the disk cache, no network.
    monkeypatch.setattr(geo, "_pois_cache", {})
    second = geo.fetch_nearest_pois(_LAT, _LON)
    assert calls["n"] == 1
    assert second == first


# --- static map ------------------------------------------------------------ #

def test_tile_frac_known_points():
    # Equator/prime meridian sits exactly in the middle of the tile grid.
    assert geo._tile_frac(0.0, 0.0, 1) == (1.0, 1.0)
    x, y = geo._tile_frac(50.08, 14.43, 15)
    assert 0 <= x <= 2**15 and 0 <= y <= 2**15


def _fake_tile_get(url, timeout=None, headers=None):
    # Pillow may be absent in images without the PDF stack — mirrors how the
    # WeasyPrint tests skip. Callers importorskip first.
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (256, 256), (200, 210, 220)).save(buf, format="PNG")

    class FakeResponse:
        content = buf.getvalue()

        def raise_for_status(self):
            pass

    return FakeResponse()


def test_render_map_produces_correctly_sized_png():
    pytest.importorskip("PIL")
    from io import BytesIO

    from PIL import Image

    png = geo._render_map(50.08, 14.43, _fake_tile_get)
    img = Image.open(BytesIO(png))
    assert img.size == (geo._MAP_W, geo._MAP_H)


def test_static_map_data_uri_failure_returns_none(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("tiles down")

    monkeypatch.setattr(geo.requests, "get", boom)
    monkeypatch.setattr(geo, "_map_cache", {})
    monkeypatch.setattr(geo.config, "LOCATION_MAP_CACHE_DIR", str(tmp_path))
    assert geo.static_map_data_uri(50.08, 14.43) is None


def test_static_map_data_uri_caches_in_process(monkeypatch, tmp_path):
    pytest.importorskip("PIL")
    calls = {"n": 0}

    def counting_get(*args, **kwargs):
        calls["n"] += 1
        return _fake_tile_get(*args, **kwargs)

    monkeypatch.setattr(geo.requests, "get", counting_get)
    monkeypatch.setattr(geo, "_map_cache", {})
    monkeypatch.setattr(geo.config, "LOCATION_MAP_CACHE_DIR", str(tmp_path))
    first = geo.static_map_data_uri(50.08, 14.43)
    second = geo.static_map_data_uri(50.08, 14.43)
    assert first is not None and first.startswith("data:image/png;base64,")
    assert first == second
    tiles_first = calls["n"]
    assert tiles_first > 0  # network hit once…
    assert calls["n"] == tiles_first  # …and served from cache the second time


def test_static_map_data_uri_persists_to_disk(monkeypatch, tmp_path):
    pytest.importorskip("PIL")
    monkeypatch.setattr(geo.requests, "get", _fake_tile_get)
    monkeypatch.setattr(geo, "_map_cache", {})
    monkeypatch.setattr(geo.config, "LOCATION_MAP_CACHE_DIR", str(tmp_path))

    uri = geo.static_map_data_uri(50.08, 14.43)
    assert uri is not None
    files = list(tmp_path.glob("*.png"))
    assert len(files) == 1
    assert files[0].read_bytes()  # non-empty PNG bytes were written


def test_static_map_data_uri_reads_disk_cache_without_network(monkeypatch, tmp_path):
    pytest.importorskip("PIL")
    calls = {"n": 0}

    def counting_get(*args, **kwargs):
        calls["n"] += 1
        return _fake_tile_get(*args, **kwargs)

    monkeypatch.setattr(geo.requests, "get", counting_get)
    monkeypatch.setattr(geo.config, "LOCATION_MAP_CACHE_DIR", str(tmp_path))

    # First call (process A): renders, hits the network, writes to disk.
    monkeypatch.setattr(geo, "_map_cache", {})
    first = geo.static_map_data_uri(50.08, 14.43)
    assert calls["n"] > 0

    # A fresh process (empty in-memory cache) must find the disk cache and
    # skip the network entirely — this is what survives a restart.
    monkeypatch.setattr(geo, "_map_cache", {})
    calls["n"] = 0
    second = geo.static_map_data_uri(50.08, 14.43)
    assert second == first
    assert calls["n"] == 0
