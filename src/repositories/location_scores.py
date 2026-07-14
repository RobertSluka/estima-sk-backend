"""location_scores repository — cached nearby-facility (POI) counts per property.

Keyed by property_id (one current score per property); re-computing upserts in
place. Durable counterpart to the in-process Overpass cache in
src/services/reports/geo.py — persists across restarts and lets a batch job
(src/services/location_scoring.py) warm coverage independently of whichever
process later serves a report.
"""

# Mirrors src.services.reports.geo.PoiCounts' fields, in the same order.
COUNT_FIELDS = (
    "nearby_transport_count_500m",
    "nearby_grocery_count_500m",
    "nearby_schools_count_1km",
    "nearby_parks_count_1km",
    "nearby_restaurants_count_1km",
    "nearby_healthcare_count_1km",
    "nearby_transport_count_1km",
    "nearby_grocery_count_1km",
    "nearby_transport_count_3km",
)


def get(cur, property_id: int) -> dict | None:
    cols = ", ".join(COUNT_FIELDS)
    cur.execute(
        f"SELECT {cols}, location_score, computed_at "
        f"FROM location_scores WHERE property_id = %s",
        (property_id,),
    )
    return cur.fetchone()


def upsert(cur, *, property_id: int, counts: dict, location_score: float | None) -> int:
    """Insert or replace the location score for one property. Returns its id.

    `counts` maps COUNT_FIELDS names to ints; missing fields become NULL.
    Unique on property_id, so recomputation overwrites the previous row.
    """
    params = {
        "property_id": property_id,
        "location_score": location_score,
        **{f: counts.get(f) for f in COUNT_FIELDS},
    }
    cur.execute(
        f"""
        INSERT INTO location_scores (
            property_id, {", ".join(COUNT_FIELDS)}, location_score, computed_at
        ) VALUES (
            %(property_id)s, {", ".join(f"%({f})s" for f in COUNT_FIELDS)},
            %(location_score)s, NOW()
        )
        ON CONFLICT (property_id) DO UPDATE SET
            {", ".join(f"{f} = EXCLUDED.{f}" for f in COUNT_FIELDS)},
            location_score = EXCLUDED.location_score,
            computed_at    = NOW()
        RETURNING id
        """,
        params,
    )
    return cur.fetchone()["id"]
