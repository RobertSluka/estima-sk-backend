"""
Feature generation: property_snapshots → property_features.

For a given feature_set (name/version/target), build one feature row per snapshot
whose deal_type matches the target (sale_* → buy, rent_* → rent). The target value
(price or price_per_sqm) is stored in its own column; it is NEVER placed inside
features_json, so training input cannot leak the target.
"""

import logging

from src.db import get_cursor
from src.repositories import feature_sets, property_features
from src.repositories.vision_scores import SCORE_FIELDS as VISION_SCORE_FIELDS

logger = logging.getLogger(__name__)

# Vision quality scores enter the feature set under a `vision_` prefix (self-
# describing, and no collision with other columns). Missing scores stay NULL —
# XGBoost handles them natively, so unscored listings still train.
VISION_FEATURE_COLUMNS = [f"vision_{field}" for field in VISION_SCORE_FIELDS]

# Ordinal encoding of canonical (human) layout codes; larger ≈ more rooms.
LAYOUT_ORDER: dict[str, int] = {
    "1+kk": 1, "1+1": 2, "2+kk": 3, "2+1": 4, "3+kk": 5, "3+1": 6,
    "4+kk": 7, "4+1": 8, "5+kk": 9, "5+1": 10, "6+kk": 11, "6+1": 12,
    "atypical": 0,
}

# The columns that make up features_json. Deliberately excludes price /
# price_per_sqm (those are the targets) to prevent leakage.
FEATURE_COLUMNS = [
    "source", "deal_type", "category", "locality", "district", "layout",
    "layout_encoded", "floor_area", "land_area", "lat", "lon",
    "market_median_price", "market_median_price_per_sqm", "market_property_count",
    *VISION_FEATURE_COLUMNS,
]

# Vision score columns, aliased with a `vision_` prefix to match the feature names.
_VISION_SELECT = ",\n        ".join(
    f"vs.{field} AS vision_{field}" for field in VISION_SCORE_FIELDS
)

_SNAPSHOT_FEATURE_SQL = f"""
    SELECT
        s.id            AS snapshot_id,
        s.property_id,
        s.snapshot_date,
        s.price,
        s.price_per_sqm,
        s.floor_area,
        s.land_area,
        s.layout,
        s.deal_type,
        s.category,
        s.locality,
        s.source,
        p.district,
        p.lat,
        p.lon,
        ms.median_price          AS market_median_price,
        ms.median_price_per_sqm  AS market_median_price_per_sqm,
        ms.property_count        AS market_property_count,
        {_VISION_SELECT}
    FROM property_snapshots s
    JOIN properties p ON p.id = s.property_id
    LEFT JOIN market_statistics ms
           ON ms.stat_date  = s.snapshot_date
          AND ms.source     = s.source
          AND ms.deal_type  = COALESCE(s.deal_type, '')
          AND ms.category   = COALESCE(s.category,  '')
          AND ms.locality   = COALESCE(s.locality,  '')
          AND ms.layout     = COALESCE(s.layout,    '')
    LEFT JOIN vision_scores vs ON vs.property_id = s.property_id
    WHERE s.deal_type = %(deal_type)s
      AND s.price IS NOT NULL
"""


def layout_encoded(layout: str | None) -> int | None:
    if not layout:
        return None
    return LAYOUT_ORDER.get(layout.lower())


def _deal_type_for_target(target: str) -> str:
    if target.startswith("sale"):
        return "buy"
    if target.startswith("rent"):
        return "rent"
    raise ValueError(f"Unknown target '{target}' (expected sale_*/rent_*)")


def _row_to_features(row: dict) -> dict:
    features = {
        "source": row["source"],
        "deal_type": row["deal_type"],
        "category": row["category"],
        "locality": row["locality"],
        "district": row["district"],
        "layout": row["layout"],
        "layout_encoded": layout_encoded(row["layout"]),
        "floor_area": float(row["floor_area"]) if row["floor_area"] is not None else None,
        "land_area": float(row["land_area"]) if row["land_area"] is not None else None,
        "lat": row["lat"],
        "lon": row["lon"],
        "market_median_price": float(row["market_median_price"]) if row["market_median_price"] is not None else None,
        "market_median_price_per_sqm": float(row["market_median_price_per_sqm"]) if row["market_median_price_per_sqm"] is not None else None,
        "market_property_count": row["market_property_count"],
    }
    # Vision scores arrive as Decimal (or NULL for unscored listings) → float/None.
    for col in VISION_FEATURE_COLUMNS:
        val = row.get(col)
        features[col] = float(val) if val is not None else None
    return features


def generate_features(*, name: str, version: str, target: str,
                      description: str | None = None) -> dict:
    """
    Materialize property_features for `target`. Returns {feature_set_id, rows}.
    """
    deal_type = _deal_type_for_target(target)
    per_sqm = target.endswith("per_sqm")

    with get_cursor() as cur:
        feature_set_id = feature_sets.get_or_create(
            cur, name=name, version=version, target=target, description=description,
        )
        cur.execute(_SNAPSHOT_FEATURE_SQL, {"deal_type": deal_type})
        rows = cur.fetchall()

        written = 0
        for row in rows:
            features = _row_to_features(row)
            property_features.upsert(
                cur,
                property_id=row["property_id"],
                snapshot_id=row["snapshot_id"],
                feature_set_id=feature_set_id,
                snapshot_date=row["snapshot_date"],
                features_json=features,
                target_price=None if per_sqm else row["price"],
                target_price_per_sqm=(float(row["price_per_sqm"])
                                      if per_sqm and row["price_per_sqm"] is not None else None),
            )
            written += 1

    logger.info("Generated %d property_features rows for feature_set %d (%s)",
                written, feature_set_id, target)
    return {"feature_set_id": feature_set_id, "rows": written}
