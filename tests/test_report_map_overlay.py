"""Tests for the facility pictograms drawn on the report's location map.

Pure: no network, no DB, no PDF engine — only the projection that decides
where a pin lands on the stitched OSM image.
"""

from __future__ import annotations

import pytest

from src.services.reports.pdf import _map_markers
from src.services.reports.schema import LocationAnalysis, NearestFacility

# Košice, Námestie osloboditeľov — the coordinate the showcase report uses.
_LAT, _LON = 48.7164, 21.2611


def _location(**overrides) -> LocationAnalysis:
    data = {
        "available": True,
        "static_map_url": "data:image/png;base64,AAAA",
        "map_center_lat": _LAT,
        "map_center_lon": _LON,
        "map_zoom": 15,
        "map_width": 1100,
        "map_height": 360,
        "nearest_facilities": [
            NearestFacility(
                category="healthcare",
                name="Dr. Max",
                distance_m=45,
                lat=48.716295,
                lon=21.260512,
            )
        ],
    }
    data.update(overrides)
    return LocationAnalysis(**data)


def test_map_markers_projects_facilities_onto_the_frame():
    overlay = _map_markers(_location())

    assert overlay["height_mm"] == pytest.approx(178 * 360 / 1100, abs=0.01)
    (marker,) = overlay["markers"]
    assert marker["category"] == "healthcare"
    # 45 m west and a little south of the centred property, at ~3.15 m/px.
    assert 48.0 < marker["left_pct"] < 50.0
    assert 50.0 < marker["top_pct"] < 51.5


def test_map_markers_is_all_or_nothing_without_geometry():
    assert _map_markers(None) is None
    assert _map_markers(_location(map_zoom=None)) is None
    assert _map_markers(_location(map_width=0)) is None


def test_map_markers_skips_facilities_without_coordinates():
    overlay = _map_markers(
        _location(
            nearest_facilities=[
                NearestFacility(category="grocery", name="Fresh", distance_m=120)
            ]
        )
    )
    assert overlay["markers"] == []


def test_map_markers_drops_facilities_outside_the_frame():
    overlay = _map_markers(
        _location(
            nearest_facilities=[
                NearestFacility(
                    category="schools",
                    name="Elsewhere",
                    distance_m=1000,
                    lat=_LAT + 0.009,  # ~1 km north of a ±570 m tall frame
                    lon=_LON,
                )
            ]
        )
    )
    assert overlay["markers"] == []
