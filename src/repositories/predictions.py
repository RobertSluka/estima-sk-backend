"""predictions repository — logged prediction requests and outputs."""

from psycopg2.extras import Json


def insert(
    cur,
    *,
    model_version_id: int,
    request_json: dict,
    features_json: dict,
    property_id: int | None = None,
    predicted_price: int | None = None,
    predicted_price_per_sqm: float | None = None,
    confidence_low: int | None = None,
    confidence_high: int | None = None,
) -> int:
    cur.execute(
        """
        INSERT INTO predictions (
            model_version_id, property_id, request_json, features_json,
            predicted_price, predicted_price_per_sqm, confidence_low, confidence_high
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (model_version_id, property_id, Json(request_json), Json(features_json),
         predicted_price, predicted_price_per_sqm, confidence_low, confidence_high),
    )
    return cur.fetchone()["id"]
