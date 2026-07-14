"""property_features repository — materialized, leakage-free features per snapshot."""

from datetime import date

from psycopg2.extras import Json


def upsert(
    cur,
    *,
    property_id: int,
    snapshot_id: int,
    feature_set_id: int,
    snapshot_date: date,
    features_json: dict,
    target_price: int | None,
    target_price_per_sqm: float | None,
) -> int:
    """
    Upsert features for one snapshot under one feature_set.

    features_json MUST NOT contain the target (price / price_per_sqm); the target
    is stored separately in target_price / target_price_per_sqm to avoid leakage.
    """
    cur.execute(
        """
        INSERT INTO property_features (
            property_id, snapshot_id, feature_set_id, snapshot_date,
            target_price, target_price_per_sqm, features_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (snapshot_id, feature_set_id) DO UPDATE SET
            target_price         = EXCLUDED.target_price,
            target_price_per_sqm = EXCLUDED.target_price_per_sqm,
            features_json        = EXCLUDED.features_json,
            snapshot_date        = EXCLUDED.snapshot_date
        RETURNING id
        """,
        (property_id, snapshot_id, feature_set_id, snapshot_date,
         target_price, target_price_per_sqm, Json(features_json)),
    )
    return cur.fetchone()["id"]
