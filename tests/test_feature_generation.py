"""Feature generation tests — pure row → features mapping.

Focus: vision scores are wired into the feature set correctly (present, prefixed,
coerced to float, NULL-safe for unscored listings).
"""

from decimal import Decimal

from src.services import feature_generation as fg


def _base_row() -> dict:
    """A snapshot row as returned by _SNAPSHOT_FEATURE_SQL (vision cols NULL)."""
    row = {
        "source": "bezrealitky", "deal_type": "rent", "category": "apartment",
        "locality": "Praha 5", "district": "Praha 5", "layout": "2+kk",
        "floor_area": Decimal("55"), "land_area": None, "lat": 50.07, "lon": 14.39,
        "market_median_price": Decimal("8000000"),
        "market_median_price_per_sqm": Decimal("160000"),
        "market_property_count": 120,
    }
    for col in fg.VISION_FEATURE_COLUMNS:
        row[col] = None
    return row


def test_vision_columns_are_in_feature_set():
    # All nine, prefixed, and part of the materialized feature contract.
    assert fg.VISION_FEATURE_COLUMNS[0] == "vision_overall_condition"
    assert len(fg.VISION_FEATURE_COLUMNS) == 9
    assert set(fg.VISION_FEATURE_COLUMNS).issubset(set(fg.FEATURE_COLUMNS))


def test_row_to_features_unscored_listing_has_null_vision():
    features = fg._row_to_features(_base_row())
    # Every vision key present (so json_normalize yields the column) but NULL.
    for col in fg.VISION_FEATURE_COLUMNS:
        assert col in features
        assert features[col] is None


def test_row_to_features_coerces_vision_decimals_to_float():
    row = _base_row()
    row["vision_overall_condition"] = Decimal("7.50")
    row["vision_natural_light"] = Decimal("9.00")
    features = fg._row_to_features(row)
    assert features["vision_overall_condition"] == 7.5
    assert isinstance(features["vision_overall_condition"], float)
    assert features["vision_natural_light"] == 9.0
    assert features["vision_kitchen_quality"] is None      # still NULL
