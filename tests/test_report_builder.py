"""Pure-function tests for src/services/reports/builder.py — no DB needed."""

from __future__ import annotations

from decimal import Decimal

from src.services.reports import builder
from src.services.reports.builder import (
    _build_location,
    _build_vision,
    _ensure_vision_row,
    _to_100,
)
from src.services.reports import geo
from src.services.reports.geo import PoiCounts
from src.services.reports.schema import MarketAnalysis, Property


def test_to_100_scales_vision_service_0_to_10_range():
    # vision_scores stores 0-10 (see tests/test_vision_scoring.py SAMPLE_SCORES);
    # this is the scale actually produced today.
    assert _to_100(8.2) == 82.0
    assert _to_100(0.0) == 0.0
    assert _to_100(10.0) == 100.0


def test_to_100_scales_legacy_0_to_1_range():
    assert _to_100(0.85) == 85.0
    assert _to_100(1.0) == 100.0


def test_to_100_passes_through_0_to_100_range():
    assert _to_100(82.0) == 82.0
    assert _to_100(100.0) == 100.0


def test_to_100_clamps_out_of_range():
    assert _to_100(150.0) == 100.0


def test_to_100_none_stays_none():
    assert _to_100(None) is None


# --- _ensure_vision_row (score-on-demand wiring) ---------------------------- #


def test_ensure_vision_row_returns_cached_row_without_scoring(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not score when a cached row exists")

    monkeypatch.setattr(builder.vision_scoring, "score_on_demand", boom)
    cached = {"overall_condition": 7.0}
    assert _ensure_vision_row({"id": 1}, cached) is cached


def test_ensure_vision_row_scores_on_demand_when_missing(monkeypatch):
    seen = {}

    def fake_score_on_demand(prop_row):
        seen.update(prop_row)
        return {"overall_condition": 8.0}

    monkeypatch.setattr(builder.vision_scoring, "score_on_demand", fake_score_on_demand)
    row = {
        "id": 42, "source": "sreality", "images": ["a.jpg"],
        "layout": "2+kk", "floor_area": 55, "district": "Praha 5",
        "name": "irrelevant field not needed by scoring",
    }
    result = _ensure_vision_row(row, None)

    assert result == {"overall_condition": 8.0}
    assert seen["id"] == 42
    assert seen["images"] == ["a.jpg"]


# --- _build_vision (photo quality only — never condition, never price) ------ #


_QUALITY_ROW = {
    "model_provider": "heuristic", "confidence": 0.7,
    "image_quality": 0.53, "brightness": 0.68, "sharpness": 0.44,
    "exposure_quality": 0.95, "resolution_quality": 0.52,
    "gallery_consistency": 0.8, "gallery_size": 6,
    "blurry_image_ratio": 0.17, "dark_image_ratio": 0.0,
    "overexposed_image_ratio": 0.0,
    # deprecated semantic block always NULL from local providers
    "overall_condition": None, "kitchen_quality": None, "photo_quality": None,
    "renovation_need": None, "interior_modernity": None, "luxury_level": None,
}
_MARKET = MarketAnalysis(estimated_value=10_000_000)

# Words that would imply the system judged the property, not the photos.
_FORBIDDEN_CLAIMS = ("renovat", "luxur", "kitchen", "bathroom", "mold",
                     "premium", "condition of the property", "in good condition")


def test_build_vision_mock_provider_renders_unavailable():
    vrow = {**_QUALITY_ROW, "model_provider": "mock", "confidence": 0.85}
    result = _build_vision(vrow, _MARKET, Property(id="1"), "en")
    assert result.available is False
    assert result.adjusted_estimate is None


def test_build_vision_reports_photo_metrics():
    result = _build_vision(dict(_QUALITY_ROW), _MARKET, Property(id="1"), "en")
    assert result.available is True
    assert result.visual_quality_score == 53.0
    assert result.brightness_score == 68.0
    assert result.sharpness_score == 44.0
    assert result.gallery_size == 6
    assert result.blurry_image_ratio == 0.17
    assert result.observations  # at least one measurable observation


def test_build_vision_never_adjusts_price_or_claims_condition():
    result = _build_vision(dict(_QUALITY_ROW), _MARKET, Property(id="1"), "en")
    assert result.overall_condition is None
    assert result.condition_adjustment_percent is None
    assert result.renovation_adjustment_percent is None
    assert result.base_estimate is None
    assert result.adjusted_estimate is None


def test_build_vision_wording_makes_no_semantic_claims():
    result = _build_vision(dict(_QUALITY_ROW), _MARKET, Property(id="1"), "en")
    # Observations must stay strictly measurable — no property-level claims.
    observations = " ".join(result.observations).lower()
    for claim in _FORBIDDEN_CLAIMS:
        assert claim not in observations, f"unsupported claim {claim!r} in: {observations}"
    # The summary must explicitly separate photo quality from property
    # condition (mentioning renovation/condition only inside that negation).
    assert "not an assessment of the property" in (result.summary or "").lower()


def test_build_vision_metricless_row_renders_unavailable():
    # Dead-gallery legacy rows and empty-attempt back-off markers carry no
    # measurable metric at all — the honest fallback, not an empty section.
    metricless = {
        "model_provider": "heuristic", "confidence": 0.0,
        "image_quality": None, "photo_quality": None, "brightness": None,
        "sharpness": None, "exposure_quality": None, "resolution_quality": None,
        "gallery_size": None, "blurry_image_ratio": None, "dark_image_ratio": None,
    }
    result = _build_vision(metricless, _MARKET, Property(id="1"), "en")
    assert result.available is False


def test_build_vision_legacy_row_falls_back_to_photo_quality():
    legacy = {
        "model_provider": "heuristic", "confidence": 0.6,
        "photo_quality": 6.5,  # 0-10 scale from heuristic-cv 0.1.0 rows
        "image_quality": None, "brightness": None, "sharpness": None,
        "exposure_quality": None, "resolution_quality": None,
        "gallery_size": None, "blurry_image_ratio": None, "dark_image_ratio": None,
    }
    result = _build_vision(legacy, _MARKET, Property(id="1"), "en")
    assert result.available is True
    assert result.visual_quality_score == 65.0
    assert result.adjusted_estimate is None


# --- _build_location (location_scores cache-first wiring) ------------------ #


class _NullCursorCtx:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def test_build_location_unavailable_without_coordinates(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not touch geo.py without coordinates")

    monkeypatch.setattr(builder.geo, "static_map_data_uri", boom)
    monkeypatch.setattr(builder.geo, "fetch_poi_counts", boom)
    monkeypatch.setattr(builder.geo, "fetch_nearest_pois", boom)

    result = _build_location(1, Property(id="1"), "en", None)
    assert result.available is False


def test_build_location_uses_cache_without_calling_overpass(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not count POIs when a cached row exists")

    monkeypatch.setattr(builder.geo, "static_map_data_uri", lambda lat, lon: "data:image/png;...")
    monkeypatch.setattr(builder.geo, "fetch_poi_counts", boom)
    monkeypatch.setattr(
        builder.geo, "fetch_nearest_pois",
        lambda lat, lon: [geo.NearestPoi(category="grocery", name="Albert", distance_m=170)],
    )

    cached_row = {
        "nearby_transport_count_500m": 9, "nearby_grocery_count_500m": 4,
        "nearby_schools_count_1km": 3, "nearby_parks_count_1km": 2,
        "nearby_restaurants_count_1km": 25, "nearby_healthcare_count_1km": 6,
        "nearby_transport_count_1km": 30, "nearby_grocery_count_1km": 11,
        "nearby_transport_count_3km": 120, "location_score": 61.5,
    }
    prop = Property(id="1", lat=50.08, lon=14.43)
    result = _build_location(1, prop, "en", cached_row)

    assert result.available is True
    assert result.nearby_transport_count_500m == 9
    assert result.location_score == 61.5
    assert [f.name for f in result.nearest_facilities] == ["Albert"]


def test_build_location_live_fetch_persists_to_cache(monkeypatch):
    upserted = {}

    monkeypatch.setattr(builder.geo, "static_map_data_uri", lambda lat, lon: "data:image/png;...")
    monkeypatch.setattr(builder.geo, "fetch_nearest_pois", lambda lat, lon: [])
    monkeypatch.setattr(
        builder.geo, "fetch_poi_counts",
        lambda lat, lon: PoiCounts(9, 4, 3, 2, 25, 6, 30, 11, 120),
    )
    monkeypatch.setattr(builder, "get_cursor", lambda: _NullCursorCtx())
    monkeypatch.setattr(
        builder.location_scores, "upsert",
        lambda cur, **kw: upserted.update(kw),
    )

    prop = Property(id="7", lat=50.08, lon=14.43)
    result = _build_location(7, prop, "en", None)

    assert result.available is True
    assert result.nearby_transport_count_500m == 9
    assert upserted["property_id"] == 7
    assert upserted["counts"]["nearby_transport_count_500m"] == 9
    assert upserted["location_score"] == result.location_score


def test_build_location_overpass_failure_degrades_without_persisting(monkeypatch):
    def fail_upsert(cur, **kw):
        raise AssertionError("should not persist when Overpass fails")

    monkeypatch.setattr(builder.geo, "static_map_data_uri", lambda lat, lon: None)
    monkeypatch.setattr(builder.geo, "fetch_poi_counts", lambda lat, lon: None)
    monkeypatch.setattr(builder.geo, "fetch_nearest_pois", lambda lat, lon: None)
    monkeypatch.setattr(builder.location_scores, "upsert", fail_upsert)

    prop = Property(id="7", lat=50.08, lon=14.43)
    result = _build_location(7, prop, "en", None)

    assert result.available is True
    assert result.nearby_transport_count_500m is None
    assert result.nearest_facilities == []
    assert result.location_score is None


# --------------------------------------------------------------------------- #
# External market benchmarks (Deloitte index)                                  #
# --------------------------------------------------------------------------- #

def _deloitte_row(**overrides) -> dict:
    row = {
        "source_name": "Deloitte Real Index",
        "metric": "realized_price_per_sqm",
        "value_czk_per_sqm": Decimal("146500"),
        "period": "2024_Q3",
        "granularity": "district",
        "district": "Praha 3",
        "city": "Praha",
    }
    row.update(overrides)
    return row


def test_build_benchmarks_maps_deloitte_district_row():
    [bench] = builder._build_benchmarks(_deloitte_row(), {"district": "Praha 3"})

    assert bench.name == "Deloitte Real Index"
    assert bench.value_per_sqm == 146500.0
    assert bench.unit == "EUR/m²"  # SK: EUR units
    assert bench.period == "Q3 2024"
    assert bench.scope == "Praha 3"


def test_build_benchmarks_city_fallback_and_rent_unit():
    [bench] = builder._build_benchmarks(
        _deloitte_row(
            source_name="Deloitte Rent Index",
            metric="realized_rent_per_sqm_month",
            value_czk_per_sqm=Decimal("466"),
            period="2026_Q1",
            granularity="city",
            district=None,
        ),
        {"district": "Neznámá čtvrť"},
    )

    assert bench.unit == "EUR/m²/month"  # SK: EUR units
    assert bench.scope == "Praha"
    assert bench.period == "Q1 2026"


def test_build_benchmarks_localizes_rent_unit():
    [bench] = builder._build_benchmarks(
        _deloitte_row(metric="realized_rent_per_sqm_month"),
        {"district": "Praha 3"},
        lang="cs",
    )

    assert bench.unit == "EUR/m²/měsíc"  # SK: EUR units


def test_build_benchmarks_empty_without_row():
    assert builder._build_benchmarks(None, {"district": "Praha 3"}) == []
    assert builder._build_benchmarks(_deloitte_row(value_czk_per_sqm=None), {}) == []
